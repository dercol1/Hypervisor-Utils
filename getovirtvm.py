#!/usr/bin/env python3

import os
import sys
import argparse
from datetime import datetime
import pandas as pd
import ovirtsdk4 as sdk
import ovirtsdk4.types as types
from tabulate import tabulate
import curses
import json


def get_input(prompt):
    return input(prompt)


def interactive_menu():
    print("\n=== RHV/oVirt VM Reporter ===")
    url = get_input(
        "Inserisci l'URL del Manager (es: https://rhvm.example.com/ovirt-engine/api): ")
    username = get_input("Inserisci username (formato: user@domain): ")
    password = get_input("Inserisci password: ")
    output_file = get_input(
        "Inserisci il nome del file di output (lascia vuoto per visualizzazione interattiva): ")
    return url, username, password, output_file


def get_vm_info(connection):
    vms_service = connection.system_service().vms_service()
    vm_list = []

    for vm in vms_service.list():
        vm_service = vms_service.vm_service(vm.id)
        vm_detail = vm_service.get()

        # Liste per memorizzare MAC e IP addresses
        mac_addresses = []
        ip_addresses = []

        # Ottieni informazioni sulle interfacce di rete
        nics_service = vm_service.nics_service()

        for nic in nics_service.list():

            # Aggiungi MAC address
            if nic.mac:
                mac_addresses.append(f"{nic.name}: {nic.mac.address}")

            # Ottieni gli indirizzi IP
            try:
                reported_devices = vm_service.reported_devices_service().list()
                for device in reported_devices:
                    if device.mac and device.mac.address == nic.mac.address:
                        for ip in device.ips:
                            ip_addresses.append(f"{nic.name}: {ip.address}")
            except Exception:
                pass

        # Ottieni informazioni sui dischi
        disks_service = vm_service.disk_attachments_service()
        disks_info = {}
        for disk_attachment in disks_service.list():
            disk = connection.follow_link(disk_attachment.disk)
            disks_info[disk.name] = {
                'size': disk.provisioned_size / (1024**3),  # Convert to GB
                'format': str(disk.format) if disk.format else 'N/A',
                'status': str(disk.status) if disk.status else 'N/A'
            }

        # Gestione sicura dei valori che potrebbero essere None
        try:
            cpu_cores = vm.cpu.topology.cores if vm.cpu and vm.cpu.topology else 0
            cpu_sockets = vm.cpu.topology.sockets if vm.cpu and vm.cpu.topology else 0
            total_cpu = cpu_cores * cpu_sockets
        except AttributeError:
            total_cpu = 0

        try:
            memory_mb = vm.memory / (1024*1024) if vm.memory else 0
        except (AttributeError, TypeError):
            memory_mb = 0

        try:
            os_type = vm.os.type if vm.os else 'N/A'
        except AttributeError:
            os_type = 'N/A'

        try:
            cluster_name = vm.cluster.name if vm.cluster else 'N/A'
        except AttributeError:
            cluster_name = 'N/A'

        try:
            host_name = vm_service.get().host.name if vm_service.get().host else 'N/A'
        except AttributeError:
            host_name = 'N/A'

        try:
            ha_enabled = str(
                vm.high_availability.enabled) if vm.high_availability else 'N/A'
        except AttributeError:
            ha_enabled = 'N/A'

        try:
            template_name = vm.template.name if vm.template else 'N/A'
        except AttributeError:
            template_name = 'N/A'

        vm_info = {
            'Nome': vm.name,
            'ID': vm.id,
            'Status': str(vm.status) if vm.status else 'N/A',
            'CPU': total_cpu,
            'Memoria (MB)': memory_mb,
            'MAC Addresses': '\n'.join(mac_addresses) if mac_addresses else 'N/A',
            'IP Addresses': '\n'.join(ip_addresses) if ip_addresses else 'N/A',
            'Sistema Operativo': os_type,
            'Cluster': cluster_name,
            'Host': host_name,
            'Disks': json.dumps(disks_info, ensure_ascii=False),
            'Creation Time': str(vm.creation_time) if vm.creation_time else 'N/A',
            'High Availability': ha_enabled,
            'Description': vm.description if vm.description else 'N/A',
            'Type': str(vm.type) if vm.type else 'N/A',
            'Template': template_name
        }
        vm_list.append(vm_info)

    return vm_list


def save_data(stdscr, data):
    stdscr.clear()
    curses.echo()
    stdscr.addstr(
        0, 0, "Inserisci il nome del file (con estensione .xlsx, .csv o .html): ")
    filename = stdscr.getstr().decode('utf-8')
    curses.noecho()

    try:
        export_data(data, filename)
        stdscr.addstr(2, 0, f"File salvato come: {filename}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        stdscr.addstr(2, 0, f"Errore nel salvataggio: {str(e)}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()


def display_interactive_table(data):
    def show_table(stdscr, data, current_row, current_col):
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        df = pd.DataFrame(data)
        table_str = tabulate(df.iloc[current_row:current_row+height-2],
                             headers='keys',
                             tablefmt='grid',
                             showindex=False)

        table_lines = table_str.split('\n')
        for i, line in enumerate(table_lines):
            if i < height-1:
                if len(line) > current_col:
                    stdscr.addstr(i, 0, line[current_col:current_col+width-1])

        help_text = "Usa frecce per navigare, 's' per salvare, 'q' per uscire"
        stdscr.addstr(height-1, 0, help_text[:width-1])
        stdscr.refresh()
        return len(df), len(table_lines[0]) if table_lines else 0

    def main(stdscr, data):
        curses.use_default_colors()
        current_row = 0
        current_col = 0

        while True:
            total_rows, max_width = show_table(
                stdscr, data, current_row, current_col)
            key = stdscr.getch()

            if key == curses.KEY_UP and current_row > 0:
                current_row -= 1
            elif key == curses.KEY_DOWN and current_row < total_rows-1:
                current_row += 1
            elif key == curses.KEY_LEFT and current_col > 0:
                current_col -= 3
            elif key == curses.KEY_RIGHT and current_col < max_width:
                current_col += 3
            elif key == ord('s'):
                save_data(stdscr, data)
            elif key == ord('q'):
                break

            current_col = max(0, current_col)

    curses.wrapper(main, data)


def export_data(data, filename):
    df = pd.DataFrame(data)

    if filename.lower().endswith('.xlsx'):
        df.to_excel(filename, index=False)
    elif filename.lower().endswith('.csv'):
        df.to_csv(filename, index=False)
    elif filename.lower().endswith('.html'):
        df.to_html(filename, index=False)
    else:
        raise ValueError(
            "Formato file non supportato. Usa .xlsx, .csv o .html")


def main():
    parser = argparse.ArgumentParser(description='RHV/oVirt VM Reporter')
    parser.add_argument('--url', help='RHV/oVirt Manager URL')
    parser.add_argument('--username', help='Username (format: user@domain)')
    parser.add_argument('--password', help='Password')
    parser.add_argument('--output', help='Output file (xlsx/csv/html)')

    args = parser.parse_args()

    if not all([args.url, args.username, args.password]):
        url, username, password, output_file = interactive_menu()
    else:
        url = args.url
        username = args.username
        password = args.password
        output_file = args.output

    try:
        connection = sdk.Connection(
            url=url,
            username=username,
            password=password,
            insecure=True,
        )

        vm_data = get_vm_info(connection)

        if output_file:
            export_data(vm_data, output_file)
            print(f"Report salvato come: {output_file}")
        else:
            display_interactive_table(vm_data)

    except Exception as e:
        print(f"Errore durante la connessione: {str(e)}")
    finally:
        if 'connection' in locals():
            connection.close()


if __name__ == "__main__":
    main()
