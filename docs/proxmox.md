# Proxmox: pass optical drive to Ubuntu VM

Your DVD burner is on the **Proxmox host** but not yet visible inside the Ubuntu VM. The web UI shows drive status; burning only works after passthrough.

## 1. Identify the drive on the Proxmox host

SSH into the Proxmox host:

```bash
lsblk
ls -l /dev/sr* /dev/cdrom 2>/dev/null
lsusb | grep -iE 'optical|dvd|cd|blu'
```

Note whether it is **USB** (common for external burners) or **SATA** (internal drive).

## 2. Pass through to the Ubuntu VM

### USB optical drive (most common)

1. Proxmox web UI → your **Ubuntu VM** → **Hardware**
2. **Add** → **USB Device**
3. Select the optical drive from the list
   - If multiple devices appear, match vendor/product from `lsusb`
4. Options:
   - **Use USB Port** — keeps the same physical port (recommended if you always use the same slot)
   - **Use USB Vendor/Device ID** — follows the device if you move ports
5. **Add**, then **reboot the VM** (or hot-plug if already running)

### SATA / onboard drive

For internal SATA optical drives, use **PCI passthrough** (requires IOMMU/VT-d enabled in BIOS):

1. Proxmox host: enable IOMMU (`intel_iommu=on` or `amd_iommu=on` in kernel cmdline)
2. Find the SATA controller or drive PCI address: `lspci`
3. VM → Hardware → Add → **PCI Device** → select the controller or drive
4. Reboot VM

USB passthrough is simpler if your drive is external USB.

## 3. Verify inside the Ubuntu VM

```bash
# After passthrough
lsblk
ls -l /dev/sr0 /dev/cdrom
sudo apt install -y wodim
wodim --devices
```

You should see something like:

```
/dev/sr0
```

Set in `.env`:

```env
DVD_DEVICE=/dev/sr0
```

## 4. Container permissions

Set `DVD_GID` in `.env` to the numeric group reported by `stat -c '%g' /dev/sr0`.
The Compose configuration passes that group to the non-root web process and maps
only the optical device; it does not use privileged mode.

## 5. Confirm in the Web UI

Open `http://<vm-ip>:8080`

- **Green pill** — `Drive ready (/dev/sr0)` → burning enabled
- **Red pill** — `No drive at /dev/sr0` → passthrough not working yet; you can still author ISOs

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Drive not in VM `lsblk` | Re-add USB device in Proxmox; reboot VM |
| `/dev/sr0` exists but container can't burn | Verify `DVD_GID` with `stat -c '%g' /dev/sr0`, restart, then check `docker compose exec web id` |
| Drive works on host but not VM | Another VM may have claimed USB; remove from other VMs |
| `growisofs: no media` | Insert blank DVD; try `wodim -prcap dev=/dev/sr0` on the VM |

After passthrough, expose port **8080** in your firewall/reverse proxy if you access the UI from your Mac.
