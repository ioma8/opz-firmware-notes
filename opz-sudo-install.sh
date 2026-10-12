#!/bin/sh
# ONE-TIME: allows the decode farm to re-insert the OP-Z update medium without
# asking you again.  Installs a sudoers rule for the single tiny tool /tmp/opzload.
set -e
echo "Installing passwordless sudo rules for the media-load tool (user: ${SUDO_USER:-$(logname)}) ..."
printf '%s ALL=(root) NOPASSWD: /tmp/opzload, %s ALL=(root) NOPASSWD: /Users/jakubkolcar/.opz-decode/opzload\n' "${SUDO_USER:-$(logname)}" "${SUDO_USER:-$(logname)}" | sudo tee /etc/sudoers.d/opzload >/dev/null
sudo visudo -c -f /etc/sudoers.d/opzload
sudo chmod 440 /etc/sudoers.d/opzload
sudo -n /tmp/opzload && echo "OK: SCSI media-load works -- the farm can now self-recover." || echo "Rule installed, but the SCSI load did not restore the medium (farm still self-resets via genuine upgrade)."
