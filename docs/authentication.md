# Authentication & Credentials Setup

Engdis Autopilot requires valid course credentials to log in. You can supply credentials via a dedicated file or environment variables.

## Option A: Credentials File (Recommended)

Create a 2-line text file containing your username and password:

```bash
mkdir -p ~/.config/engdis
cat << 'EOF' > ~/.config/engdis/cred
your_student_id_or_username
your_password
EOF
chmod 600 ~/.config/engdis/cred
```

Point `ED_CRED` to your credentials file if using a non-default location:
```bash
export ED_CRED="$HOME/.config/engdis/cred"
```

## Option B: Environment Variables

Set credentials directly in your environment or container configuration:

```bash
export ED_USER="your_student_id_or_username"
export ED_PASS="your_password"
```

## Docker Secret Mounting

In Docker Compose, mount the credentials file read-only into `/run/secrets/engdis_cred`:

```yaml
services:
  engdis:
    volumes:
      - ${ED_CRED_FILE:-/opt/data/.config/engdis/cred}:/run/secrets/engdis_cred:ro
```

Always restrict credential file permissions (`chmod 600`) to prevent unauthorized access.
