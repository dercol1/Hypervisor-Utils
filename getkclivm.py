#!/usr/bin/env python3

import os
import sys
import argparse
from datetime import datetime
import pandas as pd
from tabulate import tabulate
import curses
import json
from kvirt.config import Kconfig
from kvirt.common import error


def print_help():
    script_name = os.path.basename(sys.argv[0])
    help_text = f"""
Multi-Platform VM Reporter
========================

Uso: vmreporter.py [opzioni]

Opzioni:
  --provider   Tipo di provider (richiesto)
  --url       URL endpoint del provider
  --username  Nome utente per l'autenticazione
  --password  Password per l'autenticazione
  --output    File di output (.xlsx, .csv, .html)

Provider supportati e formati URL:
--------------------------------

1. VSphere:
   --provider vsphere --url https://vcenter.example.com
   Esempio: {script_name} --provider vsphere --url https://vcenter.company.com --username administrator@vsphere.local

2. Libvirt:
   --provider libvirt --url [qemu|xen|lxc]://hostname/system
   Esempio: {script_name} --provider libvirt --url qemu:///system
   Esempio remoto: {script_name} --provider libvirt --url qemu+ssh://user@host/system

3. oVirt/RHV:
   --provider ovirt --url https://rhvm.example.com/ovirt-engine/api
   Esempio: {script_name} --provider ovirt --url https://rhvm.company.com/ovirt-engine/api --username admin@internal

4. OpenStack:
   --provider openstack --url https://keystone.example.com:5000/v3
   Esempio: {script_name} --provider openstack --url https://controller.company.com:5000/v3

5. KubeVirt:
   --provider kubevirt --url https://k8s-api.example.com:6443
   Esempio: {script_name} --provider kubevirt --url https://kubernetes.company.com:6443

6. AWS:
   --provider aws
   Esempio: {script_name} --provider aws
   Note: Usa le credenziali dal file ~/.aws/credentials

7. GCP:
   --provider gcp
   Esempio: {script_name} --provider gcp
   Note: Richiede l'autenticazione tramite gcloud

8. IBM Cloud:
   --provider ibm --url https://cloud.ibm.com
   Esempio: {script_name} --provider ibm --url https://cloud.ibm.com

9. Proxmox:
   --provider proxmox --url https://proxmox.example.com:8006/api2/json
   Esempio: {script_name} --provider proxmox --url https://pve.company.com:8006/api2/json --username root@pam (oppure root@pve)
   Nota:
       Vengono utilizzati comandi di sistema sui nodi quindi necessario definire dei diritti per l'utente che si collega ai nodi Provider
       pveum user modify <user@pve> -groups sudo
       echo "<user> ALL=(ALL) NOPASSWD: /usr/sbin/dmidecode, /usr/bin/lspci" > /etc/sudoers.d/<user>
       chmod 440 /etc/sudoers.d/<user>



Navigazione Interattiva:
-----------------------
↑↓  Scroll verticale
←→  Scroll orizzontale
s   Salva report
q   Esci

Esempi di utilizzo:
-----------------
1. Visualizzazione interattiva VSphere:
   {script_name} --provider vsphere --url https://vcenter.example.com --username admin

2. Export diretto in Excel:
   {script_name} --provider libvirt --url qemu:///system --output vms.xlsx

3. Export in CSV per AWS:
   {script_name} --provider aws --output aws_vms.csv
"""
    print(help_text)


class VMReporter:
    def __init__(self, client_type=None, client_url=None, username=None, password=None):
        self.selected_attributes = None

        print(f"{client_type}")
        # Inizializza Kconfig solo se non viene specificato un provider specifico
        if not client_type or client_type not in ['vsphere', 'ovirt', 'libvirt', 'aws', 'gcp', 'openstack', 'kubevirt', 'ibm', 'proxmox']:
            self.config = Kconfig()
            self.client = self.config.k
        else:
            self.client_type = client_type
            self.config = None

        if client_type == 'vsphere':
            from pyVim.connect import SmartConnect
            from pyVmomi import vim
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_TLS)
            context.verify_mode = ssl.CERT_NONE
            self.client = SmartConnect(
                host=client_url.replace('https://', ''),
                user=username,
                pwd=password,
                sslContext=context
            )
        elif client_type == 'ovirt':
            import ovirtsdk4 as sdk
            try:
                connection = sdk.Connection(
                    url=client_url,
                    username=username,
                    password=password,
                    insecure=True,
                    debug=True  # Abilita il debug per vedere più dettagli
                )
                self.client = connection.system_service()
            except sdk.Error as e:
                # Estrai il contenuto della risposta dall'errore
                error_details = str(e)
                if 'text/html' in error_details:
                    print("\nRisposta del server (HTML):")
                    print("-" * 50)
                    print(error_details)
                    print("-" * 50)
                    if '/ovirt-engine/api' not in client_url:
                        print(
                            "\nSuggerimento: L'URL sembra non includere il path corretto.")
                        print("Prova ad aggiungere '/ovirt-engine/api' all'URL.")
                        print(f"Esempio: {client_url}/ovirt-engine/api")
                raise Exception(
                    f"Errore di connessione a oVirt: {error_details}")

        elif client_type == 'libvirt':
            import libvirt
            self.client = libvirt.open(client_url)

        elif client_type == 'aws':
            import boto3
            self.client = boto3.client('ec2')

        elif client_type == 'gcp':
            from google.cloud import compute_v1
            self.client = compute_v1.InstancesClient()

        elif client_type == 'openstack':
            from openstack import connection
            self.client = connection.Connection(
                auth_url=client_url,
                username=username,
                password=password
            )

        elif client_type == 'kubevirt':
            from kubernetes import client, config
            config.load_kube_config()
            self.client = client.CustomObjectsApi()

        elif client_type == 'ibm':
            from ibm_vpc import VpcV1
            from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
            # password è l'API key in questo caso
            authenticator = IAMAuthenticator(password)
            self.client = VpcV1(authenticator=authenticator)

        elif client_type == 'proxmox':
            from proxmoxer import ProxmoxAPI
            import re
            import requests
            from urllib3.exceptions import InsecureRequestWarning
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

            try:
                # Estrai l'hostname dall'URL
                base_url = re.sub(r'https?://', '', client_url)
                base_url = base_url.split(
                    ':')[0] if ':' in base_url else base_url

                # Verifica se l'username contiene il realm (@pve o @pam)
                if '@' not in username:
                    # Aggiungi @pve come default realm
                    username = f"{username}@pve"

                # Crea il client Proxmox
                try:
                    self.client = ProxmoxAPI(
                        host=base_url,
                        user=username,
                        password=password,
                        verify_ssl=False,
                        port=8006
                    )

                    # Verifica la connessione
                    version = self.client.version.get()
                    print(f"\nConnesso a Proxmox {version['version']}")

                except Exception as e:
                    print("\nErrore di autenticazione Proxmox:")
                    print("-" * 50)
                    print(f"Host: {base_url}")
                    print(f"User: {username}")
                    print(f"221 Errore: {str(e)}")
                    if hasattr(e, 'response'):
                        print("\nRisposta del server:")
                        print(f"Status: {e.response.status_code}")
                        print("Headers:", dict(e.response.headers))
                        print("Content:", e.response.text)
                    print("-" * 50)
                    raise Exception("Errore di autenticazione Proxmox")

            except Exception as e:
                print("\nErrore durante la connessione a Proxmox:")
                print("-" * 50)
                print(f"Tipo di errore: {type(e).__name__}")
                print(f"Dettagli: {str(e)}")
                if hasattr(e, 'response'):
                    print("\nRisposta del server:")
                    print(e.response.text)
                print("-" * 50)
                raise

        else:
            self.client = self.config.k

    def set_attributes(self, attributes):
        """
        Imposta gli attributi da estrarre per le VM
        """
        self.selected_attributes = attributes

    def get_vm_info(self):
        vm_list = []
        try:
            if self.client_type == 'vsphere':
                from pyVmomi import vim
                content = self.client.RetrieveContent()
                # print(f"content={content}")
                container = content.rootFolder
                vm_view = content.viewManager.CreateContainerView(
                    container, [vim.VirtualMachine], True)
                for vm in vm_view.view:
                    vm_info = self._get_vsphere_vm_info(vm)
                    vm_list.append(vm_info)

            elif self.client_type == 'ovirt':
                vms_service = self.client.vms_service()
                for vm in vms_service.list():
                    vm_info = self._get_ovirt_vm_info(vm)
                    vm_list.append(vm_info)

            elif self.client_type == 'libvirt':
                for domain in self.client.listAllDomains():
                    vm_info = self._get_libvirt_vm_info(domain)
                    vm_list.append(vm_info)

            elif self.client_type == 'aws':
                response = self.client.describe_instances()
                for reservation in response['Reservations']:
                    for instance in reservation['Instances']:
                        vm_info = self._get_aws_vm_info(instance)
                        vm_list.append(vm_info)

            elif self.client_type == 'gcp':
                project = os.getenv('GOOGLE_CLOUD_PROJECT')
                for instance in self.client.list(project=project):
                    vm_info = self._get_gcp_vm_info(instance)
                    vm_list.append(vm_info)

            elif self.client_type == 'openstack':
                for server in self.client.compute.servers():
                    vm_info = self._get_openstack_vm_info(server)
                    vm_list.append(vm_info)

            elif self.client_type == 'kubevirt':
                vms = self.client.list_cluster_custom_object(
                    group="kubevirt.io",
                    version="v1",
                    plural="virtualmachines"
                )
                for vm in vms['items']:
                    vm_info = self._get_kubevirt_vm_info(vm)
                    vm_list.append(vm_info)

            elif self.client_type == 'ibm':
                instances = self.client.list_instances().get_result()[
                    'instances']
                for instance in instances:
                    vm_info = self._get_ibm_vm_info(instance)
                    vm_list.append(vm_info)

            elif self.client_type == 'proxmox':
                for node in self.client.nodes.get():
                    for vm in self.client.nodes(node['node']).qemu.get():
                        vm_info = self._get_proxmox_vm_info(node['node'], vm)
                        vm_list.append(vm_info)

            else:
                vms = self.client.list()
                for vm in vms:
                    vm_info = self._get_generic_vm_info(vm)
                    vm_list.append(vm_info)

        except Exception as e:
            print(
                f"Errore durante il recupero delle informazioni VM: {str(e)}")

        # Applica il filtro degli attributi se specificato
        if self.selected_attributes:
            filtered_vm_list = []
            for vm in vm_list:
                filtered_vm = select_vm_attributes(
                    vm, self.selected_attributes)
                filtered_vm_list.append(filtered_vm)
            return filtered_vm_list

        return vm_list

    def get_host_info(self):
        if self.client_type == 'vsphere':
            return self.get_vsphere_host_info()
        elif self.client_type == 'proxmox':
            return self.get_proxmox_host_info()
        elif self.client_type == 'ovirt':
            return self.get_ovirt_host_info()
        else:
            return []

    # Metodi helper per ogni provider

    # VSPHERE
    def _get_vsphere_vm_info(self, vm):
        """
        Estrae le informazioni della VM da VSphere con tutti gli attributi necessari
        """
        try:
            # Raccogli informazioni sulle interfacce di rete
            network_info = []
            for nic in vm.guest.net:
                nic_info = {
                    'name': nic.deviceConfigId,
                    'mac': nic.macAddress,
                    'network': nic.network if hasattr(nic, 'network') else 'N/A',
                    'ips': nic.ipAddress if hasattr(nic, 'ipAddress') else ['N/A']
                }
                network_info.append(nic_info)

            # Raccogli informazioni sui dischi
            disk_info = []
            for device in vm.config.hardware.device:
                if hasattr(device, 'capacityInKB'):
                    disk_info.append({
                        'name': device.deviceInfo.label,
                        'size_gb': round(device.capacityInKB / (1024 * 1024), 2),
                        'interface': device.__class__.__name__.replace('vim.vm.device.', ''),
                        'format': 'N/A'  # VSphere non fornisce direttamente questo dato
                    })

            return {
                'Nome': vm.name,
                'Status': vm.runtime.powerState,
                'CPU': vm.config.hardware.numCPU,
                'Memoria_GB': round(vm.config.hardware.memoryMB / 1024, 2),
                'Network Interfaces': network_info,
                'Disks': disk_info,
                'Template': 'Yes' if vm.config.template else 'No',
                'OS': vm.config.guestFullName if hasattr(vm.config, 'guestFullName') else 'N/A',
                'Host': vm.runtime.host.name if vm.runtime.host else 'N/A',
                'Cluster': vm.runtime.host.parent.name if vm.runtime.host and vm.runtime.host.parent else 'N/A',
                'Provider': 'vsphere'
            }
        except Exception as e:
            print(
                f"Errore nel recupero delle informazioni della VM {vm.name}: {str(e)}")
            return {
                'Nome': vm.name if hasattr(vm, 'name') else 'N/A',
                'Status': 'N/A',
                'CPU': 0,
                'Memoria_GB': 0,
                'Network Interfaces': [],
                'Disks': [],
                'Template': 'N/A',
                'OS': 'N/A',
                'Host': 'N/A',
                'Cluster': 'N/A',
                'Provider': 'vsphere'
            }

    def get_vsphere_host_info(self):
        from pyVmomi import vim
        host_info = []
        content = self.client.RetrieveContent()
        host_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )

        for host in host_view.view:
            memory_info = host.hardware.memorySize
            cpu_info = host.hardware.cpuPkg[0] if host.hardware.cpuPkg else None
            pci_devices = host.hardware.pciDevice

            # Ottieni informazioni sulla memoria
            memory_modules = []
            if hasattr(host.hardware, 'memoryDeviceInfo') and host.hardware.memoryDeviceInfo:
                for memory_device in host.hardware.memoryDeviceInfo:
                    memory_modules.append({
                        # Converti in GB
                        'size': memory_device.size / (1024**3),
                        'speed': getattr(memory_device, 'speed', 'N/A'),
                        'location': getattr(memory_device, 'locator', 'N/A')
                    })
            else:
                # Se non sono disponibili informazioni dettagliate, usa la memoria totale
                memory_modules.append({
                    'size': memory_info / (1024**3),
                    'speed': 'N/A',
                    'location': 'System Memory'
                })

            host_data = {
                'nome': host.name,
                'modello': host.hardware.systemInfo.model,
                'vendor': host.hardware.systemInfo.vendor,
                'serial': host.hardware.systemInfo.serialNumber,
                'cpu_model': cpu_info.description if cpu_info else 'N/A',
                'cpu_cores': host.hardware.cpuInfo.numCpuCores,
                'cpu_threads': host.hardware.cpuInfo.numCpuThreads,
                'memoria_totale_gb': memory_info / (1024**3),
                'moduli_memoria': memory_modules,
                'pci_devices': [
                    {
                        'device': device.deviceName,
                        'vendor': device.vendorName
                    } for device in pci_devices
                ] if pci_devices else []
            }
            host_info.append(host_data)

        return host_info


# OVIRT

    def _get_ovirt_vm_info(self, vm):
        try:
            # Ottieni il servizio specifico per questa VM
            vm_service = self.client.vms_service().vm_service(vm.id)
            vm_detail = vm_service.get()

            # Ottieni informazioni sull'host
            host_name = 'N/A'
            cluster_name = 'N/A'

            if vm_detail.host:
                try:
                    host_service = self.client.hosts_service().host_service(vm_detail.host.id)
                    host = host_service.get()
                    host_name = host.name
                except Exception as e:
                    print(
                        f"Errore nel recupero delle informazioni dell'host: {str(e)}")

            if vm_detail.cluster:
                try:
                    cluster_service = self.client.clusters_service().cluster_service(vm_detail.cluster.id)
                    cluster = cluster_service.get()
                    cluster_name = cluster.name
                except Exception as e:
                    print(
                        f"Errore nel recupero delle informazioni del cluster: {str(e)}")

            # Ottieni le informazioni sulle NIC
            nics_service = vm_service.nics_service()
            nics = nics_service.list()

            # Ottieni i dispositivi riportati (per gli IP)
            reported_devices_service = vm_service.reported_devices_service()
            reported_devices = reported_devices_service.list()

            # Crea un dizionario MAC -> IPs
            mac_to_ips = {}
            for device in reported_devices:
                if device.mac and device.ips:
                    mac_to_ips[device.mac.address] = [
                        ip.address for ip in device.ips]

            # Ottieni le informazioni sui dischi
            disk_attachments_service = vm_service.disk_attachments_service()
            disk_attachments = disk_attachments_service.list()

            # Prepara la lista delle NIC con tutti i loro dettagli
            network_info = []
            for nic in nics:
                mac_address = nic.mac.address if nic.mac else 'N/A'
                nic_info = {
                    'name': nic.name,
                    'mac': mac_address,
                    'interface': str(nic.interface) if nic.interface else 'N/A',
                    'network': nic.network.name if nic.network else 'N/A',
                    'ips': mac_to_ips.get(mac_address, ['N/A'])
                }
                network_info.append(nic_info)

            # Prepara la lista dei dischi con i loro dettagli
            disk_info = []
            for attachment in disk_attachments:
                disk_service = self.client.disks_service().disk_service(attachment.disk.id)
                disk = disk_service.get()
                disk_info.append({
                    'name': disk.name,
                    'id': disk.id,
                    'size_gb': round(disk.provisioned_size / (1024**3), 2),
                    'format': str(disk.format) if disk.format else 'N/A',
                    'interface': str(attachment.interface) if attachment.interface else 'N/A',
                    'bootable': attachment.bootable,
                    'active': attachment.active
                })

            return {
                'Nome': vm_detail.name,
                'Status': str(vm_detail.status),
                'CPU': vm_detail.cpu.topology.cores if vm_detail.cpu and vm_detail.cpu.topology else 0,
                'Memoria_GB': round(vm_detail.memory / (1024**3), 2),
                'Network Interfaces': network_info,
                'Disks': disk_info,
                'Template': vm_detail.template.name if vm_detail.template else 'N/A',
                'Provider': 'ovirt',
                'OS': vm_detail.os.type if vm_detail.os else 'N/A',
                'Host': host_name,
                'Cluster': cluster.name
            }
        except Exception as e:
            print(
                f"Errore nel recupero delle informazioni della VM {vm.name}: {str(e)}")
            return {
                'Nome': vm.name if hasattr(vm, 'name') else 'N/A',
                'Status': str(vm.status) if hasattr(vm, 'status') else 'N/A',
                'CPU': 0,
                'Memoria_GB': 0,
                'Network Interfaces': [],
                'Disks': [],
                'Template': 'N/A',
                'Provider': 'ovirt',
                'OS': 'N/A',
                'Host': 'N/A',
                'Cluster': 'N/A'
            }

    def get_ovirt_host_info(self):
        host_info = []
        hosts_service = self.client.hosts_service()

        try:
            for host in hosts_service.list():
                host_service = hosts_service.host_service(host.id)
                host_detail = host_service.get()

                # Ottieni le statistiche dell'host
                stats_service = host_service.statistics_service()
                stats = stats_service.list()

                # Trova la statistica della memoria totale
                memory_total = next((
                    stat.values[0].datum
                    for stat in stats
                    if stat.name == 'memory.total'
                ), 0)

                # Ottieni informazioni sui dispositivi PCI
                devices = []
                try:
                    devices_service = host_service.devices_service()
                    for device in devices_service.list():
                        if device.capability == 'pci':
                            devices.append({
                                'device': device.product.name if device.product else 'N/A',
                                'vendor': device.vendor.name if device.vendor else 'N/A'
                            })
                except Exception as e:
                    print(f"Errore nel recupero dei dispositivi PCI: {str(e)}")

                host_data = {
                    'nome': host_detail.name,
                    'modello': host_detail.hardware_information.product_name if host_detail.hardware_information else 'N/A',
                    'vendor': host_detail.hardware_information.manufacturer if host_detail.hardware_information else 'N/A',
                    'serial': host_detail.hardware_information.serial_number if host_detail.hardware_information else 'N/A',
                    'cpu_model': host_detail.cpu.name if host_detail.cpu else 'N/A',
                    'cpu_cores': host_detail.cpu.topology.cores * host_detail.cpu.topology.sockets if host_detail.cpu and host_detail.cpu.topology else 0,
                    'cpu_threads': host_detail.cpu.topology.threads if host_detail.cpu and host_detail.cpu.topology else 0,
                    'memoria_totale_gb': memory_total / (1024**3) if memory_total else 0,
                    'moduli_memoria': [],  # oVirt non fornisce informazioni dettagliate sui moduli di memoria
                    'pci_devices': devices
                }
                host_info.append(host_data)

        except Exception as e:
            print(
                f"Errore nel recupero delle informazioni dell'host: {str(e)}")
            import traceback
            traceback.print_exc()

        return host_info


# PROXMOX

    def _oldget_proxmox_vm_info(self, node, vm):
        try:
            # Ottieni informazioni dettagliate della VM
            vm_config = self.client.nodes(node).qemu(vm['vmid']).config.get()
            vm_status = self.client.nodes(node).qemu(
                vm['vmid']).status.current.get()

            # Raccogli informazioni sulle interfacce di rete
            network_info = []
            for key, value in vm_config.items():
                if key.startswith('net'):
                    nic_info = self._parse_proxmox_net(value)
                    if nic_info:
                        network_info.append(nic_info)

            # Raccogli informazioni sui dischi
            disk_info = []
            for key, value in vm_config.items():
                if key.startswith('scsi') or key.startswith('sata') or key.startswith('ide'):
                    disk_info.append(self._parse_proxmox_disk(key, value))

            return {
                'Nome': vm['name'],
                'Status': vm_status['status'],
                'CPU': vm_status['cpus'],
                'Memoria_GB': round(vm_status['maxmem'] / (1024**3), 2),
                'Network Interfaces': network_info,
                'Disks': disk_info,
                'Template': 'Yes' if vm.get('template') == 1 else 'No',
                'Provider': 'proxmox',
                'OS': vm_config.get('ostype', 'N/A'),
                'Host': node,
                'Cluster': self.client.cluster.status.get()[0].get('name', 'N/A')
            }
        except Exception as e:
            print(
                f"Errore nel recupero delle informazioni della VM {vm['name']}: {str(e)}")
            return {
                'Nome': vm['name'],
                'Status': 'N/A',
                'CPU': 0,
                'Memoria_GB': 0,
                'Network Interfaces': [],
                'Disks': [],
                'Template': 'N/A',
                'Provider': 'proxmox',
                'OS': 'N/A',
                'Host': node,
                'Cluster': 'N/A'
            }

    def _oldparse_proxmox_net(self, net_string):
        """Analizza la stringa di configurazione della rete Proxmox"""
        try:
            parts = net_string.split(',')
            nic_info = {
                'name': 'net0',
                'mac': 'N/A',
                'interface': 'N/A',
                'network': 'N/A',
                'ips': ['N/A']
            }

            for part in parts:
                if '=' in part:
                    key, value = part.split('=')
                    if key == 'model':  # Cambiato da 'virtio' a 'model'
                        nic_info['interface'] = value
                    elif key == 'bridge':
                        nic_info['network'] = value
                    elif key == 'hwaddr':  # Cambiato da 'macaddr' a 'hwaddr'
                        nic_info['mac'] = value

            # Ottieni gli IP dalla VM
            try:
                agent_info = self.client.nodes(node).qemu(vmid).agent.get()
                if 'network-get-interfaces' in agent_info:
                    for iface in agent_info['network-get-interfaces']:
                        if iface.get('hardware-address') == nic_info['mac']:
                            nic_info['ips'] = [addr['ip-address']
                                               for addr in iface.get('ip-addresses', [])]
            except:
                pass  # Se l'agente QEMU non è disponibile, lascia gli IP come N/A

            return nic_info
        except Exception as e:
            print(f"Errore nel parsing della configurazione di rete: {str(e)}")
            return None

    def _get_proxmox_vm_info(self, node, vm):
        import traceback
        try:
            vmid = vm.get('vmid')
            if not vmid:
                raise ValueError(f"VMID non trovato per la VM nel nodo {node}")

            # Ottieni informazioni dettagliate della VM
            vm_config = self.client.nodes(node).qemu(vmid).config.get()
            vm_status = self.client.nodes(node).qemu(vmid).status.current.get()

            # Ottieni il nome della VM
            vm_name = vm_config.get('name', f"vm-{vmid}")

            # Raccogli informazioni sulle interfacce di rete
            network_info = []
            for key, value in vm_config.items():
                if key.startswith('net'):
                    nic_info = self._parse_proxmox_net(value)
                    if nic_info:
                        nic_info['name'] = key

                        # Ottieni gli IP dalla VM tramite QEMU Guest Agent, se disponibile
                        try:
                            agent_interfaces = self.client.nodes(node).qemu(
                                vmid).agent.get('network-get-interfaces')
                            for iface in agent_interfaces.get('result', []):
                                if 'hardware-address' in iface and iface['hardware-address'].lower() == nic_info['mac'].lower():
                                    ip_addresses = []
                                    for ip_info in iface.get('ip-addresses', []):
                                        if ip_info['ip-address-type'] == 'ipv4' and not ip_info['ip-address'].startswith('169.254'):
                                            ip_addresses.append(
                                                ip_info['ip-address'])
                                    nic_info['ips'] = ip_addresses if ip_addresses else [
                                        'N/A']
                        except Exception as e:
                            # Ignora se l'agente non è disponibile o altri errori
                            nic_info['ips'] = ['N/A']

                        network_info.append(nic_info)

            # Raccogli informazioni sui dischi
            disk_info = []
            for key, value in vm_config.items():
                if key.startswith(('ide', 'sata', 'scsi', 'virtio')):
                    disk = self._parse_proxmox_disk(key, value)
                    if disk:
                        disk_info.append(disk)

            # Ottieni informazioni sul cluster
            try:
                cluster_status = self.client.cluster.status.get()
                cluster_name = cluster_status[0].get(
                    'name', 'N/A') if cluster_status else 'N/A'
            except Exception:
                cluster_name = 'N/A'

            return {
                'Nome': vm_name,
                'Status': vm_status.get('status', 'N/A'),
                'CPU': vm_status.get('cpus', 0),
                'Memoria_GB': round(vm_status.get('maxmem', 0) / (1024**3), 2),
                'Network Interfaces': network_info,
                'Disks': disk_info,
                'Template': 'Yes' if vm.get('template') == 1 else 'No',
                'Provider': 'proxmox',
                'OS': vm_config.get('ostype', 'N/A'),
                'Host': node,
                'Cluster': cluster_name
            }

        except Exception as e:
            # Definisci vm_name e vmid con valori di default se non sono già definiti
            vmid = vm.get('vmid', 'Unknown')
            vm_name = vm.get('name', f"vm-{vmid}")

            print(
                f"Errore nel recupero delle informazioni della VM {vm_name} (VMID {vmid}): {str(e)}")
            traceback.print_exc()
            return {
                'Nome': vm_name,
                'Status': 'N/A',
                'CPU': 0,
                'Memoria_GB': 0,
                'Network Interfaces': [],
                'Disks': [],
                'Template': 'N/A',
                'Provider': 'proxmox',
                'OS': 'N/A',
                'Host': node,
                'Cluster': 'N/A'
            }

    def _parse_proxmox_net(self, net_string):
        """Analizza la stringa di configurazione della rete Proxmox"""
        try:
            parts = net_string.split(',')
            nic_info = {
                'mac': 'N/A',
                'interface': 'N/A',
                'network': 'N/A',
                'ips': ['N/A']
            }

            # Il primo elemento contiene il modello e il MAC address
            first_part = parts[0]
            if '=' in first_part:
                model, macaddr = first_part.split('=')
                nic_info['interface'] = model
                nic_info['mac'] = macaddr

            # Analizza gli altri parametri (es. bridge)
            for part in parts[1:]:
                if '=' in part:
                    key, value = part.split('=')
                    if key == 'bridge':
                        nic_info['network'] = value
                    # Puoi aggiungere altri parametri se necessario

            return nic_info
        except Exception as e:
            print(f"Errore nel parsing della configurazione di rete: {str(e)}")
            return None

    def _parse_proxmox_disk(self, key, value):
        """Analizza la stringa di configurazione del disco Proxmox"""
        try:
            parts = value.split(',')
            size_str = next(
                (p.split('=')[1] for p in parts if p.startswith('size=')), '0')

            # Converti size in GB
            if 'G' in size_str:
                size = float(size_str.replace('G', ''))
            elif 'M' in size_str:
                size = float(size_str.replace('M', '')) / 1024
            elif 'T' in size_str:
                size = float(size_str.replace('T', '')) * 1024
            else:
                size = float(size_str) / (1024**3)

            return {
                'name': key,
                'size_gb': round(size, 2),
                'interface': key.split('[')[0],
                'format': value.split(':')[0],
                'bootable': 'boot=1' in value
            }
        except Exception:
            return {
                'name': key,
                'size_gb': 0,
                'interface': 'N/A',
                'format': 'N/A',
                'bootable': False
            }

    def get_proxmox_host_info(self):
        host_info = []
        try:
            nodes = self.client.nodes.get()

            for node in nodes:
                try:
                    node_name = node['node']
                    node_status = self.client.nodes(node_name).status.get()

                    # Get system information using dmidecode
                    try:
                        dmi_result = self.client.nodes(node_name).execute.post(
                            'command=dmidecode -t system')['data']
                        system_info = self._parse_dmidecode_system(dmi_result)
                    except Exception as e:
                        print(f"Error getting system info: {str(e)}")
                        system_info = {'vendor': str(e),
                                       'product': 'Error', 'serial': 'Error'}

                    # Get PCI devices using lspci
                    try:
                        lspci_result = self.client.nodes(node_name).execute.post(
                            'command=lspci -v')['data']
                        pci_devices = self._parse_lspci_output(lspci_result)
                    except Exception as e:
                        print(f"Error getting PCI devices: {str(e)}")
                        pci_devices = []
                        pci_devices.append({"device": str(e),
                                            "vendor": 'N/A'})

                    # Get memory information
                    memory_total = node_status.get(
                        'memory', {}).get('total', 0)
                    try:
                        dmi_mem_result = self.client.nodes(node_name).execute.post(
                            'command=dmidecode -t memory')['data']
                        memory_modules = self._parse_dmidecode_memory(
                            dmi_mem_result)
                    except Exception as e:
                        print(f"Error getting memory info: {str(e)}")
                        memory_modules = [{
                            'size': memory_total / (1024**3),
                            'speed': 'N/A',
                            'location': 'System Memory'
                        }]

                    host_data = {
                        'nome': node_name,
                        'modello': system_info.get('product', 'N/A'),
                        'vendor': system_info.get('vendor', 'N/A'),
                        'serial': system_info.get('serial', 'N/A'),
                        'cpu_model': node_status.get('cpuinfo', {}).get('model', 'N/A'),
                        'cpu_cores': node_status.get('cpuinfo', {}).get('cores', 0),
                        'cpu_threads': node_status.get('cpuinfo', {}).get('cpus', 0),
                        'memoria_totale_gb': memory_total / (1024**3),
                        'moduli_memoria': memory_modules,
                        'pci_devices': pci_devices
                    }

                    host_info.append(host_data)

                except Exception as e:
                    print(f"Error processing node {node_name}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error getting host information: {str(e)}")

        return host_info

    def _parse_dmidecode_system(self, output):
        """Parse dmidecode system information output"""
        system_info = {}
        in_system_block = False

        for line in output.split('\n'):
            if 'System Information' in line:
                in_system_block = True
                continue
            if in_system_block:
                if line.strip().startswith('Manufacturer:'):
                    system_info['vendor'] = line.split(':', 1)[1].strip()
                elif line.strip().startswith('Product Name:'):
                    system_info['product'] = line.split(':', 1)[1].strip()
                elif line.strip().startswith('Serial Number:'):
                    system_info['serial'] = line.split(':', 1)[1].strip()
                elif line.startswith('Handle ') and system_info:
                    break

        return system_info

    def _parse_lspci_output(self, output):
        """Parse lspci output"""
        devices = []
        current_device = None

        for line in output.split('\n'):
            if line and not line.startswith('\t'):
                if current_device:
                    devices.append(current_device)
                # New device entry
                parts = line.split(' ', 1)
                if len(parts) > 1:
                    device_info = parts[1].split(':', 1)
                    if len(device_info) > 1:
                        current_device = {
                            'device': device_info[1].strip(),
                            'vendor': device_info[0].strip()
                        }

        if current_device:
            devices.append(current_device)

        return devices

    def _parse_dmidecode_memory(self, output):
        """Parse dmidecode memory information output"""
        memory_modules = []
        current_module = {}
        in_memory_device = False

        for line in output.split('\n'):
            line = line.strip()
            if 'Memory Device' in line:
                if current_module and 'size' in current_module:
                    memory_modules.append(current_module)
                current_module = {}
                in_memory_device = True
                continue

            if in_memory_device:
                if 'Size:' in line:
                    size_str = line.split(':', 1)[1].strip()
                    if 'GB' in size_str:
                        try:
                            current_module['size'] = float(
                                size_str.replace('GB', '').strip())
                        except ValueError:
                            continue
                elif 'Speed:' in line:
                    current_module['speed'] = line.split(':', 1)[1].strip()
                elif 'Locator:' in line:
                    current_module['location'] = line.split(':', 1)[1].strip()
                elif line.startswith('Handle '):
                    if current_module and 'size' in current_module:
                        memory_modules.append(current_module)
                    in_memory_device = False

        if current_module and 'size' in current_module:
            memory_modules.append(current_module)

        return memory_modules

    def oldget_proxmox_host_info(self):
        host_info = []
        try:
            nodes = self.client.nodes.get()

            for node in nodes:
                try:
                    node_name = node['node']
                    node_status = self.client.nodes(node_name).status.get()

                    # Get system information using dmidecode
                    try:
                        dmi_result = self.client.nodes(node_name).execute.post(
                            'command=dmidecode -t system')['data']
                        system_info = {}
                        for line in dmi_result.split('\n'):
                            if 'Manufacturer:' in line:
                                system_info['vendor'] = line.split(':')[
                                    1].strip()
                            elif 'Product Name:' in line:
                                system_info['product'] = line.split(':')[
                                    1].strip()
                            elif 'Serial Number:' in line:
                                system_info['serial'] = line.split(':')[
                                    1].strip()
                    except:
                        system_info = {'vendor': 'N/A',
                                       'product': 'N/A', 'serial': 'N/A'}

                    # Get PCI devices using lspci
                    try:
                        lspci_result = self.client.nodes(
                            node_name).execute.post('command=lspci')['data']
                        pci_devices = []
                        for line in lspci_result.split('\n'):
                            if line.strip():
                                # Format: "00:00.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Device 14b5"
                                parts = line.split(': ', 1)
                                if len(parts) > 1:
                                    device_info = parts[1].split(' [', 1)
                                    vendor = device_info[0]
                                    device = device_info[1].split(']')[1].strip() if len(
                                        device_info) > 1 else device_info[0]
                                    pci_devices.append({
                                        'device': device,
                                        'vendor': vendor
                                    })
                    except Exception as e:
                        print(
                            f"Error getting PCI devices for {node_name}: {str(e)}")
                        pci_devices = []

                    # Get memory information
                    memory_total = node_status.get(
                        'memory', {}).get('total', 0)
                    try:
                        dmi_mem_result = self.client.nodes(node_name).execute.post(
                            'command=dmidecode -t memory')['data']
                        memory_modules = []
                        current_module = {}
                        for line in dmi_mem_result.split('\n'):
                            line = line.strip()
                            if 'Size:' in line:
                                size = line.split(':')[1].strip()
                                if 'GB' in size:
                                    current_module['size'] = float(
                                        size.replace('GB', '').strip())
                            elif 'Speed:' in line:
                                current_module['speed'] = line.split(':')[
                                    1].strip()
                            elif 'Locator:' in line:
                                current_module['location'] = line.split(':')[
                                    1].strip()
                                if 'size' in current_module:
                                    memory_modules.append(current_module)
                                    current_module = {}
                    except:
                        memory_modules = [{
                            'size': memory_total / (1024**3),
                            'speed': 'N/A',
                            'location': 'System Memory'
                        }]

                    host_data = {
                        'nome': node_name,
                        'modello': system_info.get('product', 'N/A'),
                        'vendor': system_info.get('vendor', 'N/A'),
                        'serial': system_info.get('serial', 'N/A'),
                        'cpu_model': node_status.get('cpuinfo', {}).get('model', 'N/A'),
                        'cpu_cores': node_status.get('cpuinfo', {}).get('cores', 0),
                        'cpu_threads': node_status.get('cpuinfo', {}).get('cpus', 0),
                        'memoria_totale_gb': memory_total / (1024**3),
                        'moduli_memoria': memory_modules,
                        'pci_devices': pci_devices
                    }

                    host_info.append(host_data)

                except Exception as e:
                    print(f"Error processing node {node_name}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error getting host information: {str(e)}")

        return host_info

    def debugger_proxmox_host_info(self):
        host_info = []
        try:
            # Get nodes information
            nodes = self.client.nodes.get()

            # Debug: Salva i dati grezzi dei nodi
            with open('debug_nodes.json', 'w') as f:
                json.dump(nodes, f, indent=2)

            for node in nodes:
                try:
                    node_name = node['node']

                    # Get node status and save debug info
                    node_status = self.client.nodes(node_name).status.get()
                    with open(f'debug_{node_name}_status.json', 'w') as f:
                        json.dump(node_status, f, indent=2)

                    # Get hardware info and save debug info
                    try:
                        hw_info = self.client.nodes(node_name).hardware.get()
                        with open(f'debug_{node_name}_hardware.json', 'w') as f:
                            json.dump(hw_info, f, indent=2)
                    except:
                        hw_info = []

                    # Raccogli tutte le informazioni come prima
                    cpu_info = node_status.get('cpuinfo', {})
                    memory_total = node_status.get(
                        'memory', {}).get('total', 0)

                    # Crea la struttura dati dell'host
                    host_data = {
                        'nome': node_name,
                        'modello': 'N/A',
                        'vendor': 'N/A',
                        'serial': 'N/A',
                        'cpu_model': cpu_info.get('model', 'N/A'),
                        'cpu_cores': cpu_info.get('cores', 0),
                        'cpu_threads': cpu_info.get('cpus', 0),
                        'memoria_totale_gb': memory_total / (1024**3),
                        'moduli_memoria': [{
                            'size': memory_total / (1024**3),
                            'speed': 'N/A',
                            'location': 'System Memory'
                        }],
                        'pci_devices': [],
                        'raw_data': {
                            'node_status': node_status,
                            'hardware_info': hw_info
                        }
                    }

                    host_info.append(host_data)

                except Exception as e:
                    print(f"Error processing node {node_name}: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error getting host information: {str(e)}")

        # Salva la struttura dati completa
        with open('debug_host_info.json', 'w') as f:
            json.dump(host_info, f, indent=2)

        return host_info

    # Aggiungi metodi simili per gli altri provider

    def _get_libvirt_vm_info(self, domain):
        # Implementa la logica per libvirt
        pass

    def _get_aws_vm_info(self, instance):
        # Implementa la logica per AWS
        pass

    def _get_gcp_vm_info(self, instance):
        # Implementa la logica per GCP
        pass

    def _get_openstack_vm_info(self, server):
        # Implementa la logica per OpenStack
        pass

    def _get_kubevirt_vm_info(self, vm):
        # Implementa la logica per KubeVirt
        pass

    def _get_ibm_vm_info(self, instance):
        # Implementa la logica per IBM Cloud
        pass

    def _get_generic_vm_info(self, vm):
        return {
            'Nome': vm.get('name'),
            'Status': vm.get('status'),
            'CPU': vm.get('cpus'),
            'Memoria': vm.get('memory'),
            'MAC Address': 'N/A',
            'IP Address': vm.get('ip', 'N/A'),
            'Template': vm.get('template', 'N/A'),
            'Provider': self.client_type
        }


def display_interactive_table(data, selected_attributes):
    flat_data = []
    for vm in data:
        vm_flat = {}
        # Includi solo gli attributi selezionati
        for attr in selected_attributes:
            if attr == 'Network Interfaces':
                network_info = vm.get('Network Interfaces', [])
                network_str = []
                for nic in network_info:
                    ips_str = ', '.join(nic['ips']) if 'ips' in nic else 'N/A'
                    nic_str = f"{nic['name']}: {nic['mac']} ({nic['network']}) - IPs: {ips_str}"
                    network_str.append(nic_str)
                vm_flat[attr] = '\n'.join(
                    network_str) if network_str else 'N/A'
            elif attr == 'Disks':
                disk_info = vm.get('Disks', [])
                disk_str = []
                for disk in disk_info:
                    disk_str.append(
                        f"{disk['name']}: {disk['size_gb']}GB ({disk['interface']})")
                vm_flat[attr] = '\n'.join(disk_str) if disk_str else 'N/A'
            else:
                # Assicurati che i valori non siano None
                value = vm.get(attr)
                vm_flat[attr] = str(value) if value is not None else 'N/A'
        flat_data.append(vm_flat)

    # Crea DataFrame con gli attributi selezionati nell'ordine specificato
    df = pd.DataFrame(flat_data)
    df = df.reindex(columns=selected_attributes)

    # Ordina in base al primo attributo selezionato
    first_attr = selected_attributes[0]
    try:
        # Per colonne numeriche
        if first_attr in ['CPU', 'Memoria_GB']:
            df[first_attr] = pd.to_numeric(df[first_attr], errors='coerce')
            df = df.sort_values(by=first_attr)
        else:
            # Per colonne di testo
            df = df.sort_values(by=first_attr)
    except:
        # Se fallisce, usa l'ordinamento alfabetico standard
        df = df.sort_values(by=first_attr)

    # Sostituisci i NaN con 'N/A'
    df = df.fillna('N/A')

    # Visualizza la tabella usando curses
    curses.wrapper(lambda stdscr: _display_interactive_table(stdscr, df))


def _display_interactive_table(stdscr, df):
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    current_row = 0      # Current vertical position
    current_col = 0      # Current horizontal position
    search_mode = False  # Search mode flag
    search_query = ""    # Current search query
    search_results = []  # List of row indices matching the search
    current_search_idx = -1  # Current position in search results

    def search_table(df, query):
        """Search for query in all columns of the dataframe"""
        results = []
        for idx, row in df.iterrows():
            # Convert all values to strings and search in each cell
            row_text = ' '.join(str(val) for val in row.values)
            if query.lower() in row_text.lower():
                results.append(idx)
        return results

    while True:
        height, width = stdscr.getmaxyx()

        # Converti DataFrame in stringa tabulata
        table_str = tabulate(df, headers='keys',
                             tablefmt='grid', showindex=False)
        table_lines = table_str.split('\n')

        # Pulisci lo schermo
        stdscr.clear()

        # Mostra la tabella
        for i, line in enumerate(table_lines[current_row:current_row + height - 1]):
            if i < height - 1:
                try:
                    if len(line) > current_col:
                        stdscr.addstr(
                            i, 0, line[current_col:current_col + width - 1])
                except curses.error:
                    pass

        # Mostra la barra di aiuto
        if search_mode:
            search_text = f"Search: {search_query}"
            try:
                stdscr.addstr(height-2, 0, search_text[:width-1])
                if search_results:
                    result_text = f" ({current_search_idx + 1}/{len(search_results)})"
                    stdscr.addstr(height-2, len(search_text),
                                  result_text[:width-len(search_text)-1])
            except curses.error:
                pass

        help_text = "↑↓ Scroll verticale | ←→ Scroll orizzontale | / Search | n Next | p Prev | 's' Salva | 'q' Esci"
        try:
            stdscr.addstr(
                height - 1, 0, help_text[:width - 1], curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

        # Gestione input
        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == curses.KEY_UP and current_row > 0:
            current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(table_lines) - height:
            current_row += 1
        elif key == curses.KEY_LEFT and current_col > 0:
            current_col -= 5
        elif key == curses.KEY_RIGHT:
            current_col += 5
        elif key == curses.KEY_PPAGE:  # Page Up
            current_row = max(0, current_row - (height - 3))
        elif key == curses.KEY_NPAGE:  # Page Down
            current_row = min(len(table_lines) - height +
                              1, current_row + (height - 3))
        elif key == ord('/'):  # Enter search mode
            search_mode = True
            search_query = ""
            curses.echo()
            while True:
                try:
                    ch = stdscr.getch()
                    if ch == ord('\n'):
                        break
                    elif ch == 27:  # ESC
                        search_query = ""
                        break
                    elif ch == curses.KEY_BACKSPACE or ch == 127:
                        search_query = search_query[:-1]
                    else:
                        search_query += chr(ch)

                    # Update search results in real-time
                    search_results = search_table(df, search_query)
                    current_search_idx = 0 if search_results else -1

                    # Update display
                    stdscr.move(height-2, 8)
                    stdscr.clrtoeol()
                    stdscr.addstr(height-2, 0, f"Search: {search_query}")
                    if search_results:
                        stdscr.addstr(f" ({len(search_results)} matches)")
                    stdscr.refresh()
                except curses.error:
                    pass
            curses.noecho()
            search_mode = False

            # Jump to first result if found
            if current_search_idx >= 0:
                current_row = search_results[current_search_idx]

        elif key == ord('n'):  # Next search result
            if search_results:
                current_search_idx = (
                    current_search_idx + 1) % len(search_results)
                current_row = search_results[current_search_idx]

        elif key == ord('p'):  # Previous search result
            if search_results:
                current_search_idx = (
                    current_search_idx - 1) % len(search_results)
                current_row = search_results[current_search_idx]
        elif key == ord('s'):
            save_data(stdscr, df.to_dict('records'))


def save_data(stdscr, data):
    stdscr.clear()
    curses.echo()
    stdscr.addstr(0, 0, "Nome file (.xlsx/.csv/.html): ")
    filename = stdscr.getstr().decode('utf-8')
    curses.noecho()

    try:
        export_data(data, filename)
        stdscr.addstr(2, 0, f"Salvato come: {filename}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        stdscr.addstr(2, 0, f"1403 Errore: {str(e)}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()


def export_data(data, filename):
    df = pd.DataFrame(data)

    if filename.lower().endswith('.xlsx'):
        df.to_excel(filename, index=False)
    elif filename.lower().endswith('.csv'):
        df.to_csv(filename, index=False)
    elif filename.lower().endswith('.html'):
        df.to_html(filename, index=False)
    else:
        raise ValueError("Formato non supportato. Usa .xlsx, .csv o .html")


def get_missing_parameters(args):
    """Richiede interattivamente i parametri mancanti"""
    import getpass

    if not args.provider:
        providers = ['vsphere', 'libvirt', 'ovirt',
                     'aws', 'gcp', 'openstack', 'kubevirt', 'ibm']
        print("\nProvider disponibili:")
        for i, provider in enumerate(providers, 1):
            print(f"{i}. {provider}")
        while True:
            try:
                choice = int(input("\nSeleziona il numero del provider: ")) - 1
                if 0 <= choice < len(providers):
                    args.provider = providers[choice]
                    break
                print("Scelta non valida")
            except ValueError:
                print("Inserisci un numero valido")

    # Richiedi URL per provider che lo necessitano
    if not args.url and args.provider not in ['aws', 'gcp']:
        default_urls = {
            'vsphere': 'https://vcenter.example.com',
            'ovirt': 'https://ovirt-engine.example.com/ovirt-engine/api',
            'libvirt': 'qemu:///system',
            'openstack': 'https://keystone.example.com:5000/v3',
            'kubevirt': 'https://kubernetes.example.com:6443',
            'ibm': 'https://cloud.ibm.com',
            'proxmox': 'https://proxmox.example.com:8006/api2/json'
        }
        print(
            f"\nEsempio URL per {args.provider}: {default_urls.get(args.provider)}")
        args.url = input("Inserisci l'URL: ").strip()

    # Richiedi username per provider che lo necessitano
    if not args.username and args.provider not in ['aws', 'gcp', 'libvirt']:
        default_usernames = {
            'vsphere': 'administrator@vsphere.local',
            'ovirt': 'admin@internal',
            'openstack': 'admin',
            'kubevirt': 'admin',
            'ibm': 'apikey',
            'proxmox': 'root@pam'
        }
        print(
            f"\nUsername di default per {args.provider}: {default_usernames.get(args.provider)}")
        args.username = input("Inserisci username: ").strip()

    # Richiedi password per provider che lo necessitano
    if not args.password and args.provider not in ['aws', 'gcp', 'libvirt']:
        args.password = getpass.getpass("Inserisci password: ")

    return args


def display_host_tree(stdscr, host_data):
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    current_pos = 0      # Current cursor position
    scroll_pos = 0       # Vertical scroll position
    h_scroll_pos = 0     # Horizontal scroll position
    expanded_nodes = {}  # Dictionary to track expanded nodes
    search_mode = False  # Flag for search mode
    search_query = ""    # Current search query
    search_results = []  # List of positions matching the search
    current_search_idx = -1  # Current position in search results

    def get_tree_lines(host_data, expanded_nodes):
        lines = []
        for i, host in enumerate(host_data):
            # Livello 0: Host principale
            prefix = "└── " if i == len(host_data) - 1 else "├── "
            host_line = f"{prefix}{host['nome']}"
            if host.get('modello'):
                host_line += f" ({host['modello']})"
            lines.append((0, host_line, i))

            if (0, i) in expanded_nodes:
                # Livello 1: Categorie principali
                categories = [
                    ('CPU', f"{i}_cpu"),
                    ('Memoria', f"{i}_mem"),
                    ('PCI Devices', f"{i}_pci"),
                    ('Hardware Info', f"{i}_hw")
                ]

                for j, (category, node_id) in enumerate(categories):
                    prefix = "└── " if j == len(categories) - 1 else "├── "
                    lines.append((1, f"    {prefix}{category}", node_id))

                    # Espansione CPU
                    if category == 'CPU' and (1, node_id) in expanded_nodes:
                        cpu_info = [
                            ('Modello', host.get('cpu_model', 'N/A')),
                            ('Cores', str(host.get('cpu_cores', 'N/A'))),
                            ('Threads', str(host.get('cpu_threads', 'N/A')))
                        ]
                        for k, (label, value) in enumerate(cpu_info):
                            prefix = "└── " if k == len(
                                cpu_info) - 1 else "├── "
                            lines.append(
                                (2, f"    │   {prefix}{label}: {value}", None))

                    # Espansione Memoria
                    elif category == 'Memoria' and (1, node_id) in expanded_nodes:
                        lines.append(
                            (2, f"    │   ├── Totale: {host.get('memoria_totale_gb', 0):.2f} GB", None))
                        memory_modules = host.get('moduli_memoria', [])
                        for k, mod in enumerate(memory_modules):
                            prefix = "└── " if k == len(
                                memory_modules) - 1 else "├── "
                            lines.append(
                                (2, f"    │   {prefix}{mod.get('size', 0):.2f}GB @ {mod.get('speed', 'N/A')} ({mod.get('location', 'N/A')})", None))

                    # Espansione PCI Devices
                    elif category == 'PCI Devices' and (1, node_id) in expanded_nodes:
                        pci_devices = host.get('pci_devices', [])
                        for k, dev in enumerate(pci_devices):
                            prefix = "└── " if k == len(
                                pci_devices) - 1 else "├── "
                            lines.append(
                                (2, f"    │   {prefix}{dev.get('device', 'N/A')} ({dev.get('vendor', 'N/A')})", None))

                    # Espansione Hardware Info
                    elif category == 'Hardware Info' and (1, node_id) in expanded_nodes:
                        hw_info = [
                            ('Vendor', host.get('vendor', 'N/A')),
                            ('Serial', host.get('serial', 'N/A'))
                        ]
                        for k, (label, value) in enumerate(hw_info):
                            prefix = "└── " if k == len(
                                hw_info) - 1 else "├── "
                            lines.append(
                                (2, f"    │   {prefix}{label}: {value}", None))

        return lines

    def search_tree(lines, query):
        """Search for query in tree lines and return matching line positions"""
        results = []
        for i, (_, line, _) in enumerate(lines):
            if query.lower() in line.lower():
                results.append(i)
        return results

    while True:
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # Generate tree lines
        tree_lines = get_tree_lines(host_data, expanded_nodes)

        # Display the tree with cursor
        for i, (indent, line, node_id) in enumerate(tree_lines[scroll_pos:scroll_pos + height - 2]):
            if i < height - 2:
                try:
                    display_line = line[h_scroll_pos:h_scroll_pos + width - 1]
                    if scroll_pos + i == current_pos:
                        stdscr.attron(curses.color_pair(1))
                        stdscr.addstr(i, 0, display_line)
                        stdscr.attroff(curses.color_pair(1))
                    else:
                        stdscr.addstr(i, 0, display_line)
                except curses.error:
                    pass

        # Show help bar with search mode indicator
        help_text = "↑↓ Navigate | ←→ Scroll | PgUp/PgDn Page | Enter Expand | / Search | n Next | p Prev | 's' Save | 'q' VM List"
        if search_mode:
            search_text = f"Search: {search_query}"
            try:
                stdscr.addstr(height-2, 0, search_text[:width-1])
                stdscr.addstr(
                    height-1, 0, help_text[:width-1], curses.A_REVERSE)
            except curses.error:
                pass
        else:
            try:
                stdscr.addstr(
                    height-1, 0, help_text[:width-1], curses.A_REVERSE)
            except curses.error:
                pass

        stdscr.refresh()

        # Input handling
        key = stdscr.getch()
        if key == ord('q'):
            return True
        elif key == ord('s'):
            save_host_data(stdscr, host_data)
        elif key == ord('/'):  # Enter search mode
            search_mode = True
            search_query = ""
            curses.echo()
            while True:
                try:
                    ch = stdscr.getch()
                    if ch == ord('\n'):
                        break
                    elif ch == 27:  # ESC
                        search_query = ""
                        break
                    elif ch == curses.KEY_BACKSPACE or ch == 127:
                        search_query = search_query[:-1]
                    else:
                        search_query += chr(ch)

                    # Update search results in real-time
                    search_results = search_tree(tree_lines, search_query)
                    current_search_idx = 0 if search_results else -1

                    # Update display
                    stdscr.move(height-2, 8)
                    stdscr.clrtoeol()
                    stdscr.addstr(height-2, 0, f"Search: {search_query}")
                    stdscr.refresh()
                except curses.error:
                    pass
            curses.noecho()
            search_mode = False

            # Jump to first result if found
            if current_search_idx >= 0:
                current_pos = search_results[current_search_idx]
                scroll_pos = max(0, current_pos - (height // 2))

        elif key == ord('n'):  # Next search result
            if search_results:
                current_search_idx = (
                    current_search_idx + 1) % len(search_results)
                current_pos = search_results[current_search_idx]
                scroll_pos = max(0, current_pos - (height // 2))

        elif key == ord('p'):  # Previous search result
            if search_results:
                current_search_idx = (
                    current_search_idx - 1) % len(search_results)
                current_pos = search_results[current_search_idx]
                scroll_pos = max(0, current_pos - (height // 2))

        elif key == curses.KEY_PPAGE:  # Page Up
            scroll_amount = height - 3
            current_pos = max(0, current_pos - scroll_amount)
            scroll_pos = max(0, scroll_pos - scroll_amount)

        elif key == curses.KEY_NPAGE:  # Page Down
            scroll_amount = height - 3
            current_pos = min(len(tree_lines) - 1, current_pos + scroll_amount)
            if current_pos >= scroll_pos + height - 2:
                scroll_pos = min(len(tree_lines) - (height - 2),
                                 scroll_pos + scroll_amount)

        elif key == ord('q'):
            return True
        elif key == ord('s'):
            save_host_data(stdscr, host_data)
        elif key == curses.KEY_UP and current_pos > 0:
            current_pos -= 1
            if current_pos < scroll_pos:
                scroll_pos = current_pos
        elif key == curses.KEY_DOWN and current_pos < len(tree_lines) - 1:
            current_pos += 1
            if current_pos >= scroll_pos + height - 2:
                scroll_pos = current_pos - height + 3
        elif key == curses.KEY_LEFT and h_scroll_pos > 0:
            h_scroll_pos -= 5
        elif key == curses.KEY_RIGHT:
            h_scroll_pos += 5
        elif key == curses.KEY_PPAGE:  # Page Up
            current_pos = max(0, current_pos - (height - 3))
            scroll_pos = max(0, scroll_pos - (height - 3))
        elif key == curses.KEY_NPAGE:  # Page Down
            current_pos = min(len(tree_lines) - 1, current_pos + (height - 3))
            if current_pos >= scroll_pos + height - 2:
                scroll_pos = min(len(tree_lines) - (height - 2),
                                 scroll_pos + (height - 3))
        elif key == ord('\n'):  # Enter
            # Trova il livello e l'ID del nodo corrente
            current_line = tree_lines[current_pos]
            level = current_line[0]
            node_id = current_line[2]

            if node_id is not None:
                node_key = (level, node_id)
                if node_key in expanded_nodes:
                    expanded_nodes.pop(node_key)
                else:
                    expanded_nodes[node_key] = True

    return True


def save_host_data(stdscr, host_data):
    stdscr.clear()
    curses.echo()
    stdscr.addstr(0, 0, "Nome file per il report host (.json/.txt): ")
    filename = stdscr.getstr().decode('utf-8')
    curses.noecho()

    try:
        if filename.endswith('.json'):
            with open(filename, 'w') as f:
                json.dump(host_data, f, indent=2)
        elif filename.endswith('.txt'):
            with open(filename, 'w') as f:
                for host in host_data:
                    f.write(f"Host: {host['nome']}\n")
                    f.write(f"Modello: {host['modello']}\n")
                    f.write(
                        f"CPU: {host['cpu_model']} ({host['cpu_cores']} cores)\n")
                    f.write(
                        f"Memoria Totale: {host['memoria_totale_gb']:.2f} GB\n")
                    f.write("Moduli Memoria:\n")
                    for mod in host['moduli_memoria']:
                        f.write(
                            f"  - {mod['size']:.2f}GB @ {mod['speed']} ({mod['location']})\n")
                    f.write("\n")

        stdscr.addstr(2, 0, f"Salvato come: {filename}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        stdscr.addstr(2, 0, f"1662 Errore: {str(e)}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()


def select_vm_attributes(vm_info, selected_attributes):
    """
    Filtra gli attributi delle VM in base alla lista di attributi selezionati
    """
    filtered_info = {}
    for attr in selected_attributes:
        if attr in vm_info:
            filtered_info[attr] = vm_info[attr]
    return filtered_info


def select_attributes_interactive(provider_type):
    """
    Permette all'utente di selezionare interattivamente gli attributi desiderati
    usando un'interfaccia curses con evidenziazione e selezione tramite spazio
    """
    # Definisci gli attributi disponibili per ogni provider
    provider_attributes = {
        'vsphere': [
            'Nome', 'Status', 'CPU', 'Memoria_GB', 'Network Interfaces',
            'Disks', 'Template', 'OS', 'Host', 'Cluster', 'Provider'
        ],
        'ovirt': [
            'Nome', 'Status', 'CPU', 'Memoria_GB', 'Network Interfaces',
            'Disks', 'Template', 'OS', 'Host', 'Cluster', 'Provider'
        ],
        'proxmox': [
            'Nome', 'Status', 'CPU', 'Memoria_GB', 'Network Interfaces',
            'Disks', 'Template', 'OS', 'Host', 'Provider'
        ],
    }

    # Ottieni gli attributi disponibili per il provider specificato
    available_attributes = provider_attributes.get(provider_type, [
        'Nome', 'Status', 'CPU', 'Memoria_GB'  # Attributi di default
    ])

    def display_menu(stdscr, current_pos, selected_attrs, scroll_pos, first_selected, visible_area_height):
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # Titolo
        header = "Seleziona gli attributi da visualizzare"
        stdscr.addstr(0, 0, header, curses.A_BOLD)
        stdscr.addstr(1, 0, "-" * len(header))

        # Mostra gli attributi con scrolling
        for i, attr in enumerate(available_attributes[scroll_pos:scroll_pos + visible_area_height]):
            y_pos = i + 3
            if y_pos < height - 1:
                if attr in selected_attrs:
                    if attr == first_selected:
                        # Indicatore per l'attributo di ordinamento
                        prefix = "[O] "
                    else:
                        prefix = "[X] "
                else:
                    prefix = "[ ] "

                if scroll_pos + i == current_pos:
                    stdscr.attron(curses.color_pair(1))
                    stdscr.addstr(y_pos, 0, f"{prefix}{attr}")
                    stdscr.attroff(curses.color_pair(1))
                else:
                    stdscr.addstr(y_pos, 0, f"{prefix}{attr}")

        # Indicatori di scroll
        if scroll_pos > 0:
            stdscr.addstr(2, width-3, "↑")
        if scroll_pos + visible_area_height < len(available_attributes):
            stdscr.addstr(height-2, width-3, "↓")

        # Istruzioni
        instructions = "↑↓ Naviga | Spazio Seleziona | Enter Conferma | PgUp/PgDn Pagina"
        try:
            stdscr.addstr(
                height-1, 0, instructions[:width-1], curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

    def run_menu(stdscr):
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        current_pos = 0
        scroll_pos = 0
        selected_attrs = []
        first_selected = None
        height, _ = stdscr.getmaxyx()
        visible_area_height = height - 4  # Spazio per header e istruzioni

        while True:
            display_menu(stdscr, current_pos, selected_attrs,
                         scroll_pos, first_selected, visible_area_height)
            key = stdscr.getch()

            if key == curses.KEY_UP:
                if current_pos > 0:
                    current_pos -= 1
                    if current_pos < scroll_pos:
                        scroll_pos = current_pos
            elif key == curses.KEY_DOWN:
                if current_pos < len(available_attributes) - 1:
                    current_pos += 1
                    if current_pos >= scroll_pos + visible_area_height:
                        scroll_pos = current_pos - visible_area_height + 1
            elif key == curses.KEY_PPAGE:  # Page Up
                current_pos = max(0, current_pos - visible_area_height)
                scroll_pos = max(0, scroll_pos - visible_area_height)
            elif key == curses.KEY_NPAGE:  # Page Down
                current_pos = min(len(available_attributes) - 1,
                                  current_pos + visible_area_height)
                max_scroll = max(
                    0, len(available_attributes) - visible_area_height)
                scroll_pos = min(max_scroll, scroll_pos + visible_area_height)
            elif key == ord(' '):  # Barra spaziatrice
                attr = available_attributes[current_pos]
                if attr in selected_attrs:
                    selected_attrs.remove(attr)
                    if attr == first_selected:
                        first_selected = selected_attrs[0] if selected_attrs else None
                else:
                    selected_attrs.append(attr)
                    if first_selected is None:
                        first_selected = attr
            elif key == ord('\n'):  # Enter
                if selected_attrs:
                    if first_selected in selected_attrs:
                        selected_attrs.remove(first_selected)
                        return [first_selected] + selected_attrs
                    return selected_attrs
                else:
                    stdscr.addstr(
                        height-2, 0, "Seleziona almeno un attributo!", curses.A_BOLD)
                    stdscr.refresh()
                    stdscr.getch()

    try:
        selected_attributes = curses.wrapper(run_menu)
        return selected_attributes
    except Exception as e:
        print(f"Errore durante la selezione degli attributi: {str(e)}")
        return ['Nome', 'Status', 'CPU', 'Memoria_GB']  # Attributi di default


def main():
    parser = argparse.ArgumentParser(description='Multi-Platform VM Reporter')
    parser.add_argument('--provider', choices=['vsphere', 'libvirt', 'ovirt', 'aws', 'gcp',
                                               'openstack', 'kubevirt', 'ibm', 'proxmox'], help='Provider di virtualizzazione')
    parser.add_argument('--url', help='URL endpoint')
    parser.add_argument('--username', help='Username')
    parser.add_argument('--password', help='Password')
    parser.add_argument('--output', help='File output (xlsx/csv/html)')
    parser.add_argument('--help-full', action='store_true',
                        help='Mostra help dettagliato con esempi di URL')

    args = parser.parse_args()

    if args.help_full:
        print_help()
        return

    # Richiedi i parametri mancanti
    args = get_missing_parameters(args)

    try:
        reporter = VMReporter(args.provider, args.url,
                              args.username, args.password)
        # Prima ottieni e visualizza le informazioni degli host
        host_data = reporter.get_host_info()

        if host_data:
            show_vms = curses.wrapper(
                lambda stdscr: display_host_tree(stdscr, host_data))
            # Se l'utente ha premuto 'q', mostra le informazioni delle VM
            if show_vms:
                 # Chiedi all'utente quali attributi vuole selezionare
                selected_attributes = select_attributes_interactive(
                    args.provider)
                reporter.set_attributes(selected_attributes)
                vm_data = reporter.get_vm_info()
                if args.output:
                    export_data(vm_data, args.output, selected_attributes)
                    print(f"Report salvato come: {args.output}")
                else:
                    display_interactive_table(vm_data, selected_attributes)
        else:
            print("Nessuna informazione host disponibile")

        if args.output:
            export_data(vm_data, args.output)
            print(f"Report salvato come: {args.output}")
        else:
            display_interactive_table(vm_data, selected_attributes)

        # Stampa altre informazioni
        # print("\nInformazioni Host:")
        # for host in host_data:
        #     print(f"\nHost: {host['nome']}")
        #     print(f"Modello: {host['modello']}")
        #     print(f"CPU: {host['cpu_model']} ({host['cpu_cores']} cores)")
        #     print(f"Memoria Totale: {host['memoria_totale_gb']:.2f} GB")
        #     print("Moduli Memoria:")
        #     for mod in host['moduli_memoria']:
        #         print(
        #             f"  - {mod['size']:.2f}GB @ {mod['speed']} ({mod['location']})")

    except Exception as e:
        print(f"1876 Errore: {str(e)}")


if __name__ == "__main__":
    main()
