# Ansible deployment

This folder contains a minimal deployment for the Raspberry Pi app.

## Files

- `inventory.ini` - inventory for the Pi host.
- `group_vars/rpi.yml` - group-level application defaults.
- `host_vars/rpi_node.yml` - host-specific connection settings for the Pi.
- `site.yml` - playbook that installs dependencies, copies the app, renders `.env`, and enables the systemd service.

## Usage

1. Adjust `host_vars/rpi_node.yml` if the Pi address or SSH user changes.

2. Keep `router_password` out of the vars files and pass it at runtime, for example from the local `.env` file.

3. Run the playbook from this directory:

   ```bash
   ansible-playbook -i inventory.ini site.yml --extra-vars "router_password=YOUR_ROUTER_PASSWORD"
   ```

If you prefer, keep the router password in a local wrapper script or Ansible Vault instead of passing it directly.