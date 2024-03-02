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
    """
    Retrieve the newest image that is part of a given family in a project.

    Args:
        project: project ID or project number of the Cloud project you want to get image from.
        family: name of the image family you want to get image from.

    Returns:
        An Image object.
    """
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
    """
    Create an AttachedDisk object to be used in VM instance creation. Uses an image as the
    source for the new disk.

    Args:
         disk_type: the type of disk you want to create. This value uses the following format:
            "zones/{zone}/diskTypes/(pd-standard|pd-ssd|pd-balanced|pd-extreme)".
            For example: "zones/us-west3-b/diskTypes/pd-ssd"
        disk_size_gb: size of the new disk in gigabytes
        boot: boolean flag indicating whether this disk should be used as a boot disk of an instance
        source_image: source image to use when creating this disk. You must have read access to this disk. This can be one
            of the publicly available images or an image from one of your projects.
            This value uses the following format: "projects/{project_name}/global/images/{image_name}"
        auto_delete: boolean flag indicating whether this disk should be deleted with the VM that uses it

    Returns:
        AttachedDisk object configured to be created using the specified image.
    """
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
    """
    Waits for the extended (long-running) operation to complete.

    If the operation is successful, it will return its result.
    If the operation ends with an error, an exception will be raised.
    If there were any warnings during the execution of the operation
    they will be printed to sys.stderr.

    Args:
        operation: a long-running operation you want to wait on.
        verbose_name: (optional) a more verbose name of the operation,
            used only during error and warning reporting.
        timeout: how long (in seconds) to wait for operation to finish.
            If None, wait indefinitely.

    Returns:
        Whatever the operation.result() returns.

    Raises:
        This method will raise the exception received from `operation.exception()`
        or RuntimeError if there is no exception set, but there is an `error_code`
        set for the `operation`.

        In case of an operation taking longer than `timeout` seconds to complete,
        a `concurrent.futures.TimeoutError` will be raised.
    """
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
    """
    Send an instance creation request to the Compute Engine API and wait for it to complete.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        zone: name of the zone to create the instance in. For example: "us-west3-b"
        instance_name: name of the new virtual machine (VM) instance.
        disks: a list of compute_v1.AttachedDisk objects describing the disks
            you want to attach to your new instance.
        machine_type: machine type of the VM being created. This value uses the
            following format: "zones/{zone}/machineTypes/{type_name}".
            For example: "zones/europe-west3-c/machineTypes/f1-micro"
        network_link: name of the network you want the new instance to use.
            For example: "global/networks/default" represents the network
            named "default", which is created automatically for each project.
        subnetwork_link: name of the subnetwork you want the new instance to use.
            This value uses the following format:
            "regions/{region}/subnetworks/{subnetwork_name}"
        internal_ip: internal IP address you want to assign to the new instance.
            By default, a free address from the pool of available internal IP addresses of
            used subnet will be used.
        external_access: boolean flag indicating if the instance should have an external IPv4
            address assigned.
        external_ipv4: external IPv4 address to be assigned to this instance. If you specify
            an external IP address, it must live in the same region as the zone of the instance.
            This setting requires `external_access` to be set to True to work.
        accelerators: a list of AcceleratorConfig objects describing the accelerators that will
            be attached to the new instance.
        preemptible: boolean value indicating if the new instance should be preemptible
            or not. Preemptible VMs have been deprecated and you should now use Spot VMs.
        spot: boolean value indicating if the new instance should be a Spot VM or not.
        instance_termination_action: What action should be taken once a Spot VM is terminated.
            Possible values: "STOP", "DELETE"
        custom_hostname: Custom hostname of the new VM instance.
            Custom hostnames must conform to RFC 1035 requirements for valid hostnames.
        delete_protection: boolean value indicating if the new virtual machine should be
            protected against deletion or not.
    Returns:
        Instance object.
    """
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