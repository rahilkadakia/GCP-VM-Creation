from __future__ import annotations

import re
import sys
from typing import Any
import warnings
import time
import subprocess

from google.api_core.extended_operation import ExtendedOperation
from google.cloud import compute_v1


def get_image_from_family(project: str, family: str) -> compute_v1.Image:
    image_client = compute_v1.ImagesClient()
    # List of public operating system (OS) images: https://cloud.google.com/compute/docs/images/os-details
    newest_image = image_client.get_from_family(project=project, family=family)
    return newest_image


def disk_from_image(
    disk_type: str,
    disk_size_gb: int,
    boot: bool,
    source_image: str,
    auto_delete: bool = True,
) -> compute_v1.AttachedDisk:
    
    boot_disk = compute_v1.AttachedDisk()
    initialize_params = compute_v1.AttachedDiskInitializeParams()
    initialize_params.source_image = source_image
    initialize_params.disk_size_gb = disk_size_gb
    initialize_params.disk_type = disk_type
    boot_disk.initialize_params = initialize_params
    # Remember to set auto_delete to True if you want the disk to be deleted when you delete
    # your VM instance.
    boot_disk.auto_delete = auto_delete
    boot_disk.boot = boot
    return boot_disk


def wait_for_extended_operation(
    operation: ExtendedOperation, verbose_name: str = "operation", timeout: int = 300
) -> Any:
   
    result = operation.result(timeout=timeout)

    if operation.error_code:
        print(
            f"Error during {verbose_name}: [Code: {operation.error_code}]: {operation.error_message}",
            file=sys.stderr,
            flush=True,
        )
        print(f"Operation ID: {operation.name}", file=sys.stderr, flush=True)
        raise operation.exception() or RuntimeError(operation.error_message)

    if operation.warnings:
        print(f"Warnings during {verbose_name}:\n", file=sys.stderr, flush=True)
        for warning in operation.warnings:
            print(f" - {warning.code}: {warning.message}", file=sys.stderr, flush=True)

    return result


def create_instance(
    project_id: str,
    zone: str,
    instance_name: str,
    disks: list[compute_v1.AttachedDisk],
    machine_type: str = "g2-standard-4",
    network_link: str = "global/networks/default",
    subnetwork_link: str = None,
    internal_ip: str = None,
    external_access: bool = False,
    external_ipv4: str = None,
    accelerators: list[compute_v1.AcceleratorConfig] = None,
    preemptible: bool = False,
    spot: bool = False,
    instance_termination_action: str = "STOP",
    custom_hostname: str = None,
    delete_protection: bool = False,
) -> compute_v1.Instance:
    
    instance_client = compute_v1.InstancesClient()

    # Use the network interface provided in the network_link argument.
    network_interface = compute_v1.NetworkInterface()
    network_interface.network = network_link
    if subnetwork_link:
        network_interface.subnetwork = subnetwork_link

    if internal_ip:
        network_interface.network_i_p = internal_ip

    if external_access:
        access = compute_v1.AccessConfig()
        access.type_ = compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT.name
        access.name = "External NAT"
        access.network_tier = access.NetworkTier.PREMIUM.name
        if external_ipv4:
            access.nat_i_p = external_ipv4
        network_interface.access_configs = [access]

    # Collect information into the Instance object.
    instance = compute_v1.Instance()
    instance.network_interfaces = [network_interface]
    instance.name = instance_name
    instance.disks = disks

    # Add GPU accelerator
    gpu = compute_v1.AcceleratorConfig()
    gpu.accelerator_type = f"projects/core-verbena-328218/zones/{zone}/acceleratorTypes/nvidia-l4"  # Specify the GPU accelerator type
    gpu.accelerator_count = 1  # Specify the number of GPUs

    instance.guest_accelerators = [gpu]

    if re.match(r"^zones/[a-z\d\-]+/machineTypes/[a-z\d\-]+$", machine_type):
        instance.machine_type = machine_type
    else:
        instance.machine_type = f"zones/{zone}/machineTypes/{machine_type}"

    instance.scheduling = compute_v1.Scheduling(
        automatic_restart=True,
        on_host_maintenance="TERMINATE"
        )
    
    if accelerators:
        instance.guest_accelerators = accelerators
        instance.scheduling.on_host_maintenance = (
            compute_v1.Scheduling.OnHostMaintenance.TERMINATE.name
        )

    if preemptible:
        # Set the preemptible setting
        warnings.warn(
            "Preemptible VMs are being replaced by Spot VMs.", DeprecationWarning
        )
        instance.scheduling = compute_v1.Scheduling()
        instance.scheduling.preemptible = True

    if spot:
        # Set the Spot VM setting
        instance.scheduling.provisioning_model = (
            compute_v1.Scheduling.ProvisioningModel.SPOT.name
        )
        instance.scheduling.instance_termination_action = instance_termination_action

    if custom_hostname is not None:
        # Set the custom hostname for the instance
        instance.hostname = custom_hostname

    if delete_protection:
        # Set the delete protection bit
        instance.deletion_protection = True

    # Prepare the request to insert an instance.
    request = compute_v1.InsertInstanceRequest()
    request.zone = zone
    request.project = project_id
    request.instance_resource = instance

    # Wait for the create operation to complete.
    print(f"Creating the {instance_name} instance in {zone}...")

    operation = instance_client.insert(request=request)

    wait_for_extended_operation(operation, "instance creation")

    print(f"Instance {instance_name} created.")
    return instance_client.get(project=project_id, zone=zone, instance=instance_name)

def delete_instance(project_id, zone, instance_name):
    compute_client = compute_v1.InstancesClient()

    # Get the instance URL
    instance_url = f"projects/{project_id}/zones/{zone}/instances/{instance_name}"

    # Send the request to delete the instance
    operation = compute_client.delete(project=project_id, zone=zone, instance=instance_name)

    # Wait for the operation to complete
    print(f"Deleting instance {instance_name}...")
    print(f"Instance {instance_name} deleted successfully.")


if __name__ == "__main__":
    import google.auth
    import google.auth.exceptions

    regions = [
        "northamerica-northeast1-a",
        "southamerica-east1-a",
        "us-central1-a",
        "us-east1-c",
        "us-south1-a",
        "us-west1-a",
        "northamerica-northeast2-a",
        "us-east4-a",
        "us-east5-b",
        "us-west2-a"
    ]

    try:
        default_project_id = "core-verbena-328218"
    except google.auth.exceptions.DefaultCredentialsError:
        print(
            "Please use `gcloud auth application-default login` "
            "or set GOOGLE_APPLICATION_CREDENTIALS to use this script."
        )
    
    else:
        for region in regions:
            instance_zone = region
            instance_name = "vm-" + instance_zone

            newest_debian = get_image_from_family(
                project="ubuntu-os-cloud", family="ubuntu-2204-lts"
            )
            disk_type = f"zones/{instance_zone}/diskTypes/pd-standard"
            disks = [disk_from_image(disk_type, 20, True, newest_debian.self_link)]

            try:
                create_instance(default_project_id, instance_zone, instance_name, disks, external_access=True)

            except google.api_core.exceptions.Forbidden:
                print("#### GPU Exists in this region. Delete VM with that GPU first. ####")

            except google.api_core.exceptions.BadRequest:
                print(f"#### GPU doesn't exist in region {instance_zone}. Try another region ####")

            except google.api_core.exceptions.ServiceUnavailable:
                print(f"#### Region {instance_zone} doesn't have the resources to fulfill request ####")
            
            except google.api_core.exceptions.Conflict:
                print(f"#### VM instance with this GPU already exists in {instance_zone} ####")

            else:
                print(f"#### GPU Successfully added in VM in region {instance_zone} ####")
                compute_client = compute_v1.InstancesClient()
                instance_details = compute_client.get(project=default_project_id, zone=instance_zone, instance=instance_name)

                vm_instance_ip = instance_details.network_interfaces[0].access_configs[0].nat_i_p
                vm_username = "Dell"

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} echo 'works'"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt update"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt upgrade"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt install ubuntu-drivers-common"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt install nvidia-driver-535"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo reboot now"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt install gcc"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo dpkg -i cuda-keyring_1.1-1_all.deb"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt-get update"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo reboot now"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} sudo apt install nvidia-cuda-toolkit"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} nvidia-smi"
                subprocess.run(ssh_command, shell=True)

                ssh_command = f"ssh -i id_rsa {vm_username}@{vm_instance_ip} nvcc --version"
                subprocess.run(ssh_command, shell=True)

                delete_instance(default_project_id, instance_zone, instance_name)
                time.sleep(30)