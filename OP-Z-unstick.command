#!/bin/bash
# Double-click this to un-stick the OP-Z update medium.  It asks for your Mac
# password once, installs a one-line sudoers rule for the tiny SCSI loader, then
# re-inserts the OP-Z medium so the firmware decode farm (already running) resumes.
cd "$(dirname "$0")"
echo "=== OP-Z media re-insert ==="
if [ ! -x /tmp/opzload ]; then echo "ERROR: /tmp/opzload missing (rebuild with cc)"; read -n1; exit 1; fi
printf '%s ALL=(root) NOPASSWD: /tmp/opzload\n' "$(whoami)" | sudo tee /etc/sudoers.d/opzload >/dev/null || { echo "sudo failed"; read -n1; exit 1; }
sudo chmod 440 /etc/sudoers.d/opzload
echo "--- sending SCSI START STOP UNIT (load media) ---"
sudo -n /tmp/opzload
# poll: the volume can take up to ~30 s to appear, and it may mount as "OP-Z 1"
for i in $(seq 1 15); do
  if ls -d /Volumes/OP-Z* >/dev/null 2>&1; then
    echo "*** SUCCESS: $(ls -d /Volumes/OP-Z*) is back -- the decode farm is resuming now."
    echo "The rule stays installed, so the farm re-inserts the medium by itself from now on."
    echo; echo "You can close this window."; exit 0
  fi
  sleep 2
done
echo "--- volume not up yet. Try the command once more; if it stays absent, power-cycle the OP-Z once"
echo "--- (press PLAY) -- the farm then self-resets forever after each cycle."
