import os
import time
import logging
from avocado.core import exceptions

from virttest import virsh
from virttest.utils_test import libvirt
from virttest import data_dir
from virttest.libvirt_xml import vm_xml
from virttest.libvirt_xml import snapshot_xml


def run(test, params, env):
    """Shallow blockcommit on different storage backend layer
    block commit chain: base <-- layer1 <-- layer2 <-- layer3
    storage type on every layer: file, block, gluster, nbd, rbd, iscsi
    Test steps:
    1. Create snapshot on layer1, layer2, layer3.
    2. Do shallow blockcommit from top for 3 times.
    3. Clean environment.
    """
    def make_or_clean_snapshot(layer, params, is_setup):
        """Make snapshot for one layer
        Args:
            layer(str): layer of snapshot, could be 'layer1', 'layer2', 'layer3'
            params: env params
            is_setup(bool): True for setup snapshot, False for cleanup
        Returns:
            If complete setup, return snapshot xml, else return None.
        """
        if is_setup:
            logging.debug("Creating storage env for %s", layer)
            vm_name = params.get("main_vm")
            snap_type = params.get("snapshot")
            layer_type = params.get(layer + "_type")
            logging.debug("layer type is %s", layer_type)
            snap_xml = snapshot_xml.SnapshotXML()
            snap_xml.snap_name = layer
            snap_disk_xml = snap_xml.SnapDiskXML()
            snap_disk_xml.disk_name = vm_xml.VMXML.new_from_inactive_dumpxml(
                vm_name).devices.by_device_tag('disk')[0].target['dev']
            snap_disk_xml.snapshot = snap_type
            if layer_type == "file":
                file_path = os.path.join(
                    data_dir.get_tmp_dir(), layer + '.qcow2')
                snap_disk_xml.source = snap_disk_xml.new_disk_source(
                    **{'attrs': {'file': file_path}})
                logging.debug("The snapshot disk xml is: %s",
                              snap_disk_xml.xmltreefile)
            if layer_type == "block":
                snap_disk_xml.type_name = 'block'
                dev_path = libvirt.setup_or_cleanup_iscsi(
                    is_setup=True, is_login=True, emulated_image=layer)
                snap_disk_xml.source = snap_disk_xml.new_disk_source(
                    **{'attrs': {'dev': dev_path}})
                logging.debug("The snapshot disk xml is: %s",
                              snap_disk_xml.xmltreefile)
            if layer_type == "glusterfs":
                brick_path = params.get(layer + "_brick_path")
                os.mkdir(brick_path)
                snap_disk_xml.type_name = 'network'
                img_name = layer + '/' + layer + ".qcow2"
                host_ip = libvirt.setup_or_cleanup_gluster(
                    is_setup=True, vol_name=layer, brick_path=brick_path)
                source_dict = {'protocol': 'gluster', 'name': img_name}
                host_dict = [{"name": host_ip}]
                snap_disk_xml.source = snap_disk_xml.new_disk_source(
                    **{'attrs': source_dict, "hosts": host_dict})
                logging.debug("The snapshot disk xml is: %s",
                              snap_disk_xml.xmltreefile)
            if layer_type == "nbd":
                pass
            if layer_type == "rbd":
                pass
            if layer_type == "iscsi":
                pass
            snap_xml.set_disks([snap_disk_xml])
            logging.debug("The snapshot xml is: %s", snap_xml.xmltreefile)
            return snap_xml

        if not is_setup:
            layer_type = params.get(layer + "_type")
            if layer_type == "file":
                return
            if layer_type == "block":
                libvirt.setup_or_cleanup_iscsi(
                    is_setup=False, emulated_image=layer)
                time.sleep(2)
            if layer_type == "glusterfs":
                brick_path = params.get(layer + "_brick_path")
                libvirt.setup_or_cleanup_gluster(
                    is_setup=False, vol_name=layer, brick_path=brick_path)
            if layer_type == "nbd":
                pass
            if layer_type == "rbd":
                pass
            if layer_type == "iscsi":
                pass

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    disk_target = vm_xml.VMXML.new_from_inactive_dumpxml(
        vm_name).devices.by_device_tag('disk')[0].target['dev']

    try:
        vm.start()
        for layer in ["layer1", "layer2", "layer3"]:
            snap_xml = make_or_clean_snapshot(layer, params, is_setup=True)
            logging.debug("Creating storage env for %s", layer)
            snap_options = "%s --disk-only --no-metadata" % snap_xml.xml
            snap_result = virsh.snapshot_create(
                vm_name, snap_options, debug=True)
            if snap_result.exit_status != 0:
                raise exceptions.TestFail(snap_result.stderr)

        commit_options = "--active --shallow --wait --verbose --pivot"
        for layer in ["layer1", "layer2", "layer3"]:
            logging.debug("Shallow blockcommit from %s", layer)
            commit_result = virsh.blockcommit(
                vm_name, disk_target, commit_options, debug=True)
            if commit_result.exit_status != 0:
                raise exceptions.TestFail(commit_result.stderr)

    finally:
        if vm.is_alive():
            vm.destroy()
        for layer in ["layer1", "layer2", "layer3"]:
            snap_xml = make_or_clean_snapshot(layer, params, is_setup=False)
        vmxml_backup.sync()
