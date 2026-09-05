import { BleManager, Device, Subscription } from "react-native-ble-plx";
import { PermissionsAndroid, Platform } from "react-native";
import { base64Decode, base64Encode } from "./base64";
import {
  CHARACTERISTIC_CONTROL,
  CHARACTERISTIC_IMU,
  CHARACTERISTIC_LIVE_STATUS,
  CHARACTERISTIC_RIDE_DATA,
  CHARACTERISTIC_SPEED,
  SERVICE_UUID,
} from "./protocol";
import type { PiRideSummary } from "../types/ride";

export interface LiveStatus {
  riskLevel: number;
  eventFlag: number;
}

/** IMU 담당 팀원이 정의한 스키마 그대로 (BLE_PROTOCOL.md 2-4 참고) */
export interface ImuStatus {
  connected: boolean;
  roll: number;
  pitch: number;
  ax: number;
  ay: number;
  az: number;
  acc_magnitude: number;
  impact: boolean;
  rollover: boolean;
}

const RIDE_DATA_CHUNK_TIMEOUT_MS = 5000;

export class RideDataStalledError extends Error {
  constructor() {
    super("주행기록 수신이 중간에 멈췄습니다 (청크 유실 가능성)");
  }
}

export class BleService {
  private manager = new BleManager();
  private device: Device | null = null;

  async requestAndroidPermissions(): Promise<boolean> {
    if (Platform.OS !== "android") return true;
    if (Platform.Version >= 31) {
      const result = await PermissionsAndroid.requestMultiple([
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      ]);
      return Object.values(result).every(
        (status) => status === PermissionsAndroid.RESULTS.GRANTED
      );
    }
    const granted = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION
    );
    return granted === PermissionsAndroid.RESULTS.GRANTED;
  }

  isConnected(): boolean {
    return this.device !== null;
  }

  /** 지금 연결된 기기가 끊기면 콜백을 호출한다. 연결된 게 없으면 즉시 에러. */
  onDeviceDisconnected(callback: () => void): Subscription {
    const device = this.requireDevice();
    return device.onDisconnected(() => callback());
  }

  getConnectedMac(): string | null {
    return this.device?.id ?? null;
  }

  async connectByMac(mac: string): Promise<void> {
    const device = await this.manager.connectToDevice(mac, { timeout: 10000 });
    await device.discoverAllServicesAndCharacteristics();

    this.device = device;
    device.onDisconnected(() => {
      if (this.device?.id === device.id) this.device = null;
    });
  }

  async disconnect(): Promise<void> {
    if (!this.device) return;
    await this.manager.cancelDeviceConnection(this.device.id).catch(() => {});
    this.device = null;
  }

  private requireDevice(): Device {
    if (!this.device) throw new Error("파이와 연결되어 있지 않습니다");
    return this.device;
  }

  async sendStart(): Promise<void> {
    await this.writeControl(0x01);
  }

  /** 현재 주행 속도를 파이로 보낸다 (collision zone 크기 조정용). 실패해도 라이딩엔
   * 영향 없어야 하므로 조용히 무시 — 파이는 갱신이 끊기면 알아서 기본값으로 폴백함. */
  async writeSpeed(speedKmh: number): Promise<void> {
    if (!this.device) return;
    const raw = Math.max(0, Math.min(65535, Math.round(speedKmh * 10)));
    const bytes = new Uint8Array([raw & 0xff, (raw >> 8) & 0xff]);
    try {
      await this.manager.writeCharacteristicWithResponseForDevice(
        this.device.id,
        SERVICE_UUID,
        CHARACTERISTIC_SPEED,
        base64Encode(bytes)
      );
    } catch {
      // 속도 전송 실패는 무시 — 다음 GPS 샘플에서 다시 시도됨
    }
  }

  private async writeControl(command: number): Promise<void> {
    const device = this.requireDevice();
    const value = base64Encode(new Uint8Array([command]));
    await this.manager.writeCharacteristicWithResponseForDevice(
      device.id,
      SERVICE_UUID,
      CHARACTERISTIC_CONTROL,
      value
    );
  }

  subscribeLiveStatus(onUpdate: (status: LiveStatus) => void): Subscription {
    const device = this.requireDevice();
    return this.manager.monitorCharacteristicForDevice(
      device.id,
      SERVICE_UUID,
      CHARACTERISTIC_LIVE_STATUS,
      (error, characteristic) => {
        if (error || !characteristic?.value) return;
        const bytes = base64Decode(characteristic.value);
        if (bytes.length < 2) return;
        onUpdate({ riskLevel: bytes[0], eventFlag: bytes[1] });
      }
    );
  }

  /** JSON 문자열 그대로 오는 IMU 값 구독 (청크 분할 없음, BLE_PROTOCOL.md 2-4 참고) */
  subscribeImu(onUpdate: (status: ImuStatus) => void): Subscription {
    const device = this.requireDevice();
    return this.manager.monitorCharacteristicForDevice(
      device.id,
      SERVICE_UUID,
      CHARACTERISTIC_IMU,
      (error, characteristic) => {
        if (error || !characteristic?.value) return;
        try {
          const bytes = base64Decode(characteristic.value);
          const json = new TextDecoder().decode(bytes);
          onUpdate(JSON.parse(json) as ImuStatus);
        } catch {
          // 파싱 실패한 패킷은 무시하고 다음 알림을 기다림
        }
      }
    );
  }

  async stopRideAndReceiveData(): Promise<PiRideSummary> {
    const device = this.requireDevice();

    return new Promise<PiRideSummary>((resolve, reject) => {
      const chunks = new Map<number, Uint8Array>();
      let lastChunkSeq: number | null = null;
      let timeoutHandle: ReturnType<typeof setTimeout>;
      let subscription: Subscription | null = null;

      const cleanup = () => {
        clearTimeout(timeoutHandle);
        subscription?.remove();
      };

      const resetTimeout = () => {
        clearTimeout(timeoutHandle);
        timeoutHandle = setTimeout(() => {
          cleanup();
          reject(new RideDataStalledError());
        }, RIDE_DATA_CHUNK_TIMEOUT_MS);
      };

      subscription = this.manager.monitorCharacteristicForDevice(
        device.id,
        SERVICE_UUID,
        CHARACTERISTIC_RIDE_DATA,
        (error, characteristic) => {
          if (error || !characteristic?.value) return;
          const bytes = base64Decode(characteristic.value);
          if (bytes.length < 3) return;

          const seq = bytes[0] | (bytes[1] << 8);
          const isLast = bytes[2] === 1;
          const payload = bytes.slice(3);
          chunks.set(seq, payload);
          if (isLast) lastChunkSeq = seq;
          resetTimeout();

          if (lastChunkSeq !== null && chunks.size === lastChunkSeq + 1) {
            cleanup();
            try {
              const total = new Uint8Array(
                [...chunks.entries()]
                  .sort(([a], [b]) => a - b)
                  .flatMap(([, part]) => [...part])
              );
              const json = new TextDecoder().decode(total);
              resolve(JSON.parse(json) as PiRideSummary);
            } catch (parseError) {
              reject(parseError);
            }
          }
        }
      );

      resetTimeout();

      this.writeControl(0x02).catch((err) => {
        cleanup();
        reject(err);
      });
    });
  }

  destroy(): void {
    this.manager.destroy();
  }
}

export const bleService = new BleService();
