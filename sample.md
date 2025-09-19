# Dronetag Device Configuration Sample

This sample automates the full settings upload process for the device. It follows these steps:

1. Connect to device
   Opens the serial SLIP connection to the given MUX_PATH.

2. Read current settings
   Fetches the current JSON configuration from the device.

3. Check device lock status
- If the device is unlocked, the script:
	- Uploads an initial `acl_0` and `key_0` pair.
	- Locks the device with "settings/lock": true.
- If the device is already locked, it skips directly to signed settings.

4. Prepare signed settings
- Fetches the device serial number.
- Signs the new settings JSON using AES-CCM with the configured AUTH_KEY.
- Sends the signed JSON to the device.

5. Verify settings
   Reads back the applied settings and checks that the changes match the intended values.

6. Restart the device
   Sends a restart command and waits until the device reconnects.
   Once reconnected, it reads back settings again to confirm restart success.

This means the script can be run directly on both - unlocked and already locked devices, handling the initial setup automatically.

---

## How to Run

You can run the script as a module.

```bash
sudo python -m device-configuration-sample.main
```

> **_NOTE:_** `sudo` is usually required to access /dev/ttyACM* unless you have proper udev permissions.

---

## Regenerating protobuf files

The project includes a generated Python file `fwinfo_utils/protos/dt_fwinfo_pb2.py` from the protobuf definition `fwinfo_utils/protos/dt_fwinfo.proto`.  
If you encounter runtime errors about mismatched protobuf versions, you can regenerate the file with:

```bash
protoc --python_out=. dt_fwinfo.proto
```
This will update `dt_fwinfo_pb2.py` to match your installed protobuf runtime.