# Dronetag Device Configuration

Dronetag devices support configuration over the **USB (serial port)** or **Bluetooth** (not covered in this manual). Configuration is performed by sending JSON packets with the desired settings. Its based on a lightweight transport stack that ensures all data is reliably framed and routed to the correct service inside the device.

For a practical demonstration of this process, see the **[Sample Overview](sample.md)**.

---
## Communication Stack

All communication with a Dronetag device is built on the following layers:

1. **SLIP framing**
    - Each packet is framed using the SLIP protocol
    - Special marker bytes (`END`, `ESC`) are used so the receiver knows where a packet starts/ends.
    - This ensures raw serial streams can carry discrete messages without ambiguity.

2. **MUX channels**
    - The first byte of each SLIP payload is a **channel ID**.
    - Each inner service (e.g., settings, firmware info, logs) has its own channel.
    - Examples:
        - `settings0` → `SETTINGS_MUX_ADDR` = `0x13`
        - `fwinfo0` → `FWINFO_MUX_ADDR` = `0x12`

3. **Application payload**
    - After the channel byte, the actual payload is sent:
        - JSON packets (for settings)
        - Protobuf packets (for firmware info, status, etc.)

### Reassembly of Packets

- A single logical JSON response may be split across **multiple SLIP frames**.
- The host must:
    - Collect and reassemble fragments.
    - Decode them from SLIP.
    - Concatenate the JSON parts until a full object is formed.
Example:
- Device sends a JSON response like:
``` json
{"app/brightness":25, "dt_log_mux/enable":true}
```
- Over the wire, this may arrive as two separate SLIP packets:
    - `RX chunk: {"app/brightness":25`
    - `RX chunk: ,"dt_log_mux/enable":true}`
- The host must stitch these back into a single JSON object before parsing.

---
# Basic configuration

When the device is **unlocked**, configuration is simple: send JSON packets with the desired settings to the address `SETTINGS_MUX_ADDR`.
``` json
{
  "app/brightness": 25,
  "save": true
}
```

---
# Locked Configuration with Authentication

If the device firmware has the **authentication** settings feature enabled, configuration can be locked.
In this mode, only users who possess a valid authentication key can change the settings.

Signed JSON packets are required. Their structure is:
``` json
{
  "cnt": "<base64-encoded JSON configuration payload>",
  "sig": "<base64-encoded signature, generated using the authentication key>"
}
```
- The **authentication key** is a **32-byte** secret stored on the device.
- The device can store up to 3 different authentication keys.
- Each key is associated with an Access Control (**ACL**) **vector**.
- The ACL vector defines which settings a key grants access to.

### ACL Vector

- The ACL vector is a **32-byte array** (256 bits total).
- Each bit corresponds to one ACL group.
- Example:
    - A vector with only one bit set → access to a single group.
    - A vector of all `0xFF` bytes → access to all groups.
- ACL vectors must be stored in **base64 encoding**.

**Example: Access to** `app/brightness`

Lets assume the setting `app/brightness` belongs to **ACL group 10**.
- To grant access only to this group, you must set **bit 10** in the ACL vector.
- The result is a 32-byte vector where only that bit is `1`:

Hex representation:
```
00 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Explanation:
- Bit numbering starts from the **least significant bit of the first byte** (`bit 0`).
- Setting bit 10 means `0x04` in the **second byte** (since bits 8–15 are in byte 1).

Base64 encoding of this vector:
```
AAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
```

This vector would allow access only to ACL group 10 and therefore to `app/brightness`.

### Authentication Key

- The **authentication key** is the 32-byte array used to sign configuration settings for a **locked** device.
- Each key is associated with an ACL vector (e.g. `/settings/key_0` ↔ `/settings/acl_0`). The device supports up to three keys (`key_0`, `key_1`, `key_2`) and three corresponding ACL vectors.
	Mapping:
    - `/settings/key_0` → authentication key (write only)
    - `/settings/acl_0` → ACL vector providing access rights for `key_0`
    - etc.
- The key **must be uploaded** to the device in **base64** form and is **write-only** - once stored on the device it cannot be read back. Keep a copy of the key in a secure place. If you lose the key, you cannot manage a locked device.
- The key is used by the host tool to create signatures: the tool base64-encodes the JSON payload (this becomes `cnt`), then signs it with **AES-CCM** using the 32-byte key (device expects a fixed 13-byte zero nonce). The AES-CCM authentication tag is base64-encoded and sent as `sig`.

---
## Step-by-Step Setup

To configure a device for **locked mode**, follow these steps:

### 1. Store the ACL Vector

This defines what access rights the associated key will have.
- Example: Full access (32 × `0xFF`):
    - Base64 encoded: `///////////////////////////////////////////8=`
- Store it under the key `/settings/acl_0`.
- This setting **is readable** (you can verify it after writing).
- JSON packet:
``` json
{
  "settings/acl_0": "//////////////////////////////////////////8=",
  "save": true
}
```
### 2. Store the Authentication Key

This is the secret used for signing JSON packets.
- Must be a random 32-byte value.
- Must be base64 encoded.
- Store it under the key `/settings/key_0`.
- **Important:** `/settings/key_0` is **write-only**. Once written, it cannot be read back!  
    Keep a safe copy of the key. Without it, you cannot reconfigure a locked device.

Example key (hexadecimal, 32 bytes):
```
0a 00 32 99 15 20 19 10 18 20 13 13 73 18 20 11
cd a4 ed 8b 51 aa 2c bb cc 5f dd 94 13 1a ef 24
```

Base64 encoded:
```
CgAymRUgGRAYIBMTcxggEc2k7YtRqiy7zF/dlBMa7yQ=
```

JSON packet:
``` json
{
  "settings/key_0": "CgAymRUgGRAYIBMTcxggEc2k7YtRqiy7zF/dlBMa7yQ=",
  "save": true
}
```

### 3. Lock the Device

- The device **cannot** be locked unless at least one authentication key is already stored.
- Locking is not automatic — it must be explicitly enabled.
- Lock status is stored under `/settings/lock`.
JSON packet:
``` json
{
  "settings/lock": true,
  "save": true
}
```

At this point, the device is **locked**. Further configuration changes require **signed JSON packets** generated using the authentication key.

---
## Writing Settings to a Locked Device

Once a Dronetag device is locked, the raw JSON settings wont be applied anymore. Instead, you must send a **signed JSON packet** over the proper MUX channel, wrapped in **SLIP encoding**.

1. **Read Device Serial Number**
    - Send a protobuf request on the `fwinfo0` channel to query device info.
    - Wait for the device to respond with its serial number.
    - Example request (protobuf):
```
req {
  cmd: READ_DEVICE_INFO
}
```
- Example response (protobuf):
```
res {
  dev_info {
    serial_number: "1596A30AC452E72"
  }
}
```

2. **Assemble JSON Payload**
- Include both your desired settings and the device serial number:
``` json
{
  "app/brightness": 5,
  "sn": "1596A30AC452E72",
  "save": true
}
```

3. **Encode and Sign**

- Base64-encode the full JSON object → becomes `"cnt"`.
- Sign it with **AES-CCM** using:
    - The 32-byte authentication key (`/settings/key_0` etc.).
    - Fixed 13-byte zero nonce.
    - The base64-encoded JSON as input.
- AES-CCM produces an authentication tag → base64-encode it as `"sig"`.
Final signed JSON packet looks like:
``` json
{
  "cnt": "eyJhcHAvYnJpZ2h0bmVzcyI6IDUsICJzbiI6ICIxNTk2QTMwQUM0NTJFNzIiLCAic2F2ZSI6IHRydWV9",
  "sig": "3LqgLbYHt6Xz0tKcVJ1vRA=="
}
```

4. **Send Signed Packet**
- Wrap the JSON with the settings channel address and SLIP encoding.
- Example:
``` 
[SETTINGS_MUX_ADDR] + json.dumps(signed_packet)
```

5. **Verify Applied Settings**
- After sending, issue a verification request:
``` json
{}
```
(an empty JSON object).
- This instructs the device to return its current configuration state.
- The handler reassembles JSON (responses may come split across multiple SLIP frames).

6. **Compare Device Response**
- The response is checked against the original request (minus write-only keys like `save` or `settings/key_0`).
- Example:
```
Device returned 'app/brightness' = 25
All settings verified
```

---
### Important Notes
- Verification is not automatic: you must explicitly send `{}` after writing and compare the values.
- Some keys (`save`, `reset`, or authentication keys themselves) cannot be read back, as they are write-only.
- If the device responds with a mismatch, you should retry or report the discrepancy.