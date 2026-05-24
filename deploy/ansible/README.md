# Ansible deployment

This folder contains a minimal deployment for the Raspberry Pi app.

## Files

- `inventory.ini.example` - sample inventory for the Pi.
- `group_vars/all.yml.example` - local deployment variables, including the router password placeholder.
- `site.yml` - playbook that installs dependencies, copies the app, renders `.env`, and enables the systemd service.

## Usage

1. Copy the example inventory to a local file:

   ```bash
   cp inventory.ini.example inventory.ini
   ```

2. Copy the example variables file and set the real password:

   ```bash
   cp group_vars/all.yml.example group_vars/all.yml
   ```

3. Run the playbook from this directory:

   ```bash
   ansible-playbook -i inventory.ini site.yml
   ```

If you prefer, store `group_vars/all.yml` with Ansible Vault instead of a plain file.