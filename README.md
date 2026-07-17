# Photo Hub

Photo Hub is a self-hosted Raspberry Pi service that receives emailed photos
and delivers them to an Aura frame, a Samsung The Frame TV, or both.

It is designed for a small, trusted group of senders. Incoming images are
normalized to metadata-stripped sRGB JPEGs before delivery.

> [!IMPORTANT]
> Photo Hub processes private photos and stores email and device credentials.
> Run it only on a trusted host and network, keep the configuration file out of
> source control, and use a dedicated Gmail account with an App Password.

Photo Hub is an independent project and is not affiliated with or endorsed by
Google, Aura, or Samsung.

## Features

- Accepts a single JPEG, PNG, TIFF, HEIC, or HEIF attachment by email.
- Restricts submissions to configured sender addresses.
- Sends normalized photos to an Aura frame by email.
- Queues photos for Samsung The Frame without interrupting ordinary viewing.
- Keeps only the newest pending TV photo.
- Deletes only the previous TV content ID recorded by Photo Hub.
- Includes a conservative TV capability probe for validating a device before
  enabling uploads.

## How it works

Email one photo attachment to the dedicated Gmail account. Start the subject or
the first non-empty body line with one destination command:

- `frame`: submit to Aura only
- `tv`: queue/display on Samsung The Frame only
- `both`: submit to Aura now and queue/display on Samsung The Frame

If the TV is unavailable, the newest TV-directed image remains pending. Photo
Hub does not turn on Art Mode.

## Requirements

- Python 3.9 or newer
- A dedicated Gmail account with IMAP enabled and an App Password
- An Aura frame contributor email address, a compatible Samsung The Frame TV,
  or both
- A Linux host for continuous operation; the included service file targets a
  Raspberry Pi running systemd

Samsung support depends on the TV firmware and the Art API exposed on the local
network. The current implementation uses the `samsungtvws` Art client on port
`8001` and has been validated with the LS03B model family. Test your own device
with the read-only probe commands before enabling TV delivery.

## Installation

Using [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked
```

Or using a standard virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .
```

## Configuration

Copy the example to a private location and replace every placeholder:

```bash
mkdir -p ~/.config/photo-hub
cp config.example.json ~/.config/photo-hub/config.json
chmod 600 ~/.config/photo-hub/config.json
```

Required values:

- `gmail.email`: the dedicated Gmail address
- `gmail.app_password`: a Gmail App Password, not the account password
- `allowed_senders`: email addresses authorized to submit photos
- `aura.frame_email`: the Aura frame's unique email address
- `tv.host`: the Samsung TV's local IP address
- `paths.state_dir`: a private directory for the database, images, and device
  state

The Gmail account must be invited as a contributor to the Aura frame. If only
Aura delivery is needed, set `tv.enabled` to `false`.

Validate the configuration before starting the service:

```bash
uv run photo-hub --config ~/.config/photo-hub/config.json check-config
```

## Usage

Run one processing pass:

```bash
uv run photo-hub --config ~/.config/photo-hub/config.json once
```

Run continuously:

```bash
uv run photo-hub --config ~/.config/photo-hub/config.json run
```

Show local state:

```bash
uv run photo-hub --config ~/.config/photo-hub/config.json status
```

Check TV Art Mode without uploading anything:

```bash
uv run photo-hub --config ~/.config/photo-hub/config.json tv-status
```

## systemd

The example unit in `systemd/photo-hub.service` expects the checkout at
`/home/pi/photo-hub` and the configuration at
`/home/pi/.config/photo-hub/config.json`. Adjust the user and paths for your
host, then install it:

```bash
sudo cp systemd/photo-hub.service /etc/systemd/system/photo-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now photo-hub.service
```

Follow service logs with:

```bash
sudo journalctl -u photo-hub.service -f
```

## TV compatibility probe

Start with read-only checks, replacing the example address with the TV's local
IP:

```bash
uv run photo-hub-tv-probe --host 192.168.1.50 preflight
uv run photo-hub-tv-probe --host 192.168.1.50 --homebridge-art status
```

Upload, replacement, and cleanup commands are intentionally explicit:

```bash
uv run photo-hub-tv-probe --host 192.168.1.50 --homebridge-art upload-first
uv run photo-hub-tv-probe --host 192.168.1.50 --homebridge-art replace
uv run photo-hub-tv-probe --host 192.168.1.50 --homebridge-art cleanup --confirm
```

Run upload commands only while the TV is already in Art Mode. The probe records
the content IDs it creates and refuses to delete unrecorded content.

## Development

```bash
uv sync --locked --extra test
uv run --frozen pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.

## License

Photo Hub is available under the [MIT License](LICENSE).
