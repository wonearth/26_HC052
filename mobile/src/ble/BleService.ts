import { BleManager, Device, Subscription } from "react-native-ble-plx";
import { PermissionsAndroid, Platform } from "react-native";
import { base64Decode, base64Encode } from "./base64";
import {
  CHARACTERISTIC_CONTROL,
  CHARACTERISTIC_LIVE_STATUS,
  CHARACTERISTIC_PHONE_GPS,
  CHARACTERISTIC_RIDE_DATA,
  SERVICE_UUID,
} from "./protocol";
import type { RidePayload } from "../types/ride";

export interface LiveStatus {
  riskLevel: number;
  eventFlag: number;
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

  getConnectedMac(): string | null {
    return this.device?.id ?? null;
  }

  async connectByMac(mac: string): Promise<void> {
    const device = await this.manager.connectToDevice(mac, { timeout: 10000 });
    await device.discoverAllServicesAndCharacteristics();

    const chars = await device.characteristicsForService(SERVICE_UUID);
    chars.forEach((c) => {
      console.log("===== CHARACTERISTIC =====");
      console.log("UUID:", c.uuid);
      console.log("isWritableWithResponse:", c.isWritableWithResponse);
      console.log("isWritableWithoutResponse:", c.isWritableWithoutResponse);
      console.log("isNotifiable:", c.isNotifiable);
    });

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

  async sendPhoneGps(lat: number, lng: number, speedKmh: number): Promise<void> {
    const device = this.requireDevice();
    const json = JSON.stringify({
      lat,
      lng,
      speed_kmh: Math.max(0, speedKmh),
    });
    const bytes = new TextEncoder().encode(json);
    const value = base64Encode(bytes);

    await this.manager.writeCharacteristicWithoutResponseForDevice(
      device.id,
      SERVICE_UUID,
      CHARACTERISTIC_PHONE_GPS,
      value
    );
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

  async stopRideAndReceiveData(): Promise<RidePayload> {
    const device = this.requireDevice();

    return new Promise<RidePayload>((resolve, reject) => {
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
              resolve(JSON.parse(json) as RidePayload);
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
