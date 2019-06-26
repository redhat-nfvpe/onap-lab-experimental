#  Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import abc
import binascii
import functools
import json
from multiprocessing.pool import ThreadPool
import os
import re
import shlex
import time

from ironic_lib import disk_utils
from ironic_lib import utils as il_utils
import netaddr
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
import pint
import psutil
import pyudev
import six
import stevedore
import yaml

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import netutils
from ironic_python_agent import utils

_global_managers = None
LOG = log.getLogger()
CONF = cfg.CONF

WARN_BIOSDEVNAME_NOT_FOUND = False

UNIT_CONVERTER = pint.UnitRegistry(filename=None)
UNIT_CONVERTER.define('bytes = []')
UNIT_CONVERTER.define('MB = 1048576 bytes')
_MEMORY_ID_RE = re.compile(r'^memory(:\d+)?$')
NODE = None

SUPPORTED_SOFTWARE_RAID_LEVELS = frozenset(['0', '1', '1+0'])


def _get_device_info(dev, devclass, field):
    """Get the device info according to device class and field."""
    try:
        devname = os.path.basename(dev)
        with open('/sys/class/%s/%s/device/%s' % (devclass, devname, field),
                  'r') as f:
            return f.read().strip()
    except IOError:
        LOG.warning(
            "Can't find field {} for device {} in device class {}".format(
                field, dev, devclass))


def _get_system_lshw_dict():
    """Get a dict representation of the system from lshw

    Retrieves a json representation of the system from lshw and converts
    it to a python dict

    :return: A python dict from the lshw json output
    """
    out, _e = utils.execute('lshw', '-quiet', '-json', log_stdout=False)
    return json.loads(out)


def _udev_settle():
    """Wait for the udev event queue to settle.

    Wait for the udev event queue to settle to make sure all devices
    are detected once the machine boots up.

    """
    try:
        utils.execute('udevadm', 'settle')
    except processutils.ProcessExecutionError as e:
        LOG.warning('Something went wrong when waiting for udev '
                    'to settle. Error: %s', e)
        return


def _check_for_iscsi():
    """Connect iSCSI shared connected via iBFT or OF.

    iscsistart -f will print the iBFT or OF info.
    In case such connection exists, we would like to issue
    iscsistart -b to create a session to the target.
    - If no connection is detected we simply return.
    """
    try:
        utils.execute('iscsistart', '-f')
    except (processutils.ProcessExecutionError, EnvironmentError) as e:
        LOG.debug("No iscsi connection detected. Skipping iscsi. "
                  "Error: %s", e)
        return
    try:
        utils.execute('iscsistart', '-b')
    except processutils.ProcessExecutionError as e:
        LOG.warning("Something went wrong executing 'iscsistart -b' "
                    "Error: %s", e)


def _get_component_devices(raid_device):
    """Get the component devices of a Software RAID device.

    Examine an md device and return its constituent devices.

    :param raid_device: A Software RAID block device name.
    :returns: A list of the component devices.
    """
    if not raid_device:
        return []

    component_devices = []
    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        msg = ('Could not get component devices of %(dev)s: %(err)s' %
               {'dev': raid_device, 'err': e})
        raise errors.SoftwareRAIDError(msg)

    lines = out.splitlines()
    for line in lines:
        if 'active sync' not in line:
            continue
        device = re.findall(r'/dev/\w+', line)
        component_devices += device

    return component_devices


def get_holder_disks(raid_device):
    """Get the holder disks of a Software RAID device.

    Examine an md device and return its underlying disks.

    :param raid_device: A Software RAID block device name.
    :returns: A list of the holder disks.
    """
    if not raid_device:
        return []

    holder_disks = []

    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        msg = ('Could not get holder disks of %(dev)s: %(err)s' %
               {'dev': raid_device, 'err': e})
        raise errors.SoftwareRAIDError(msg)

    lines = out.splitlines()
    for line in lines:
        if 'active sync' not in line:
            continue
        device = re.findall(r'/dev/\D+', line)
        holder_disks += device

    return holder_disks


def is_md_device(raid_device):
    """Check if a device is an md device

    Check if a device is a Software RAID (md) device.

    :param raid_device: A Software RAID block device name.
    :returns: True if the device is an md device, False otherwise.
    """
    try:
        utils.execute('mdadm', '--detail', raid_device)
        LOG.debug("%s is an md device", raid_device)
        return True
    except processutils.ProcessExecutionError:
        LOG.debug("%s is not an md device", raid_device)
        return False


def md_restart(raid_device):
    """Restart an md device

    Stop and re-assemble a Software RAID (md) device.

    :param raid_device: A Software RAID block device name.
    :raises: CommandExecutionError in case the restart fails.
    """
    try:
        component_devices = _get_component_devices(raid_device)
        utils.execute('mdadm', '--stop', raid_device)
        utils.execute('mdadm', '--assemble', raid_device,
                      *component_devices)
    except processutils.ProcessExecutionError as e:
        error_msg = ('Could not restart md device %(dev)s: %(err)s' %
                     {'dev': raid_device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def list_all_block_devices(block_type='disk',
                           ignore_raid=False):
    """List all physical block devices

    The switches we use for lsblk: P for KEY="value" output, b for size output
    in bytes, i to ensure ascii characters only, and o to specify the
    fields/columns we need.

    Broken out as its own function to facilitate custom hardware managers that
    don't need to subclass GenericHardwareManager.

    :param block_type: Type of block device to find
    :param ignore_raid: Ignore auto-identified raid devices, example: md0
                        Defaults to false as these are generally disk
                        devices and should be treated as such if encountered.
    :return: A list of BlockDevices
    """

    def _is_known_device(existing, new_device_name):
        """Return true if device name is already known."""
        for known_dev in existing:
            if os.path.join('/dev', new_device_name) == known_dev.name:
                return True
        return False

    _udev_settle()

    # map device names to /dev/disk/by-path symbolic links that points to it

    by_path_mapping = {}

    disk_by_path_dir = '/dev/disk/by-path'

    try:
        paths = os.listdir(disk_by_path_dir)

        for path in paths:
            path = os.path.join(disk_by_path_dir, path)
            # Turn possibly relative symbolic link into absolute
            devname = os.path.join(disk_by_path_dir, os.readlink(path))
            devname = os.path.abspath(devname)
            by_path_mapping[devname] = path

    except OSError as e:
        # NOTE(TheJulia): This is for multipath detection, and will raise
        # some warning logs with unrelated tests.
        LOG.warning("Path %(path)s is inaccessible, /dev/disk/by-path/* "
                    "version of block device name is unavailable "
                    "Cause: %(error)s", {'path': disk_by_path_dir, 'error': e})

    columns = ['KNAME', 'MODEL', 'SIZE', 'ROTA', 'TYPE']
    report = utils.execute('lsblk', '-Pbi', '-o{}'.format(','.join(columns)),
                           check_exit_code=[0])[0]
    lines = report.splitlines()
    context = pyudev.Context()

    devices = []
    for line in lines:
        device = {}
        # Split into KEY=VAL pairs
        vals = shlex.split(line)
        for key, val in (v.split('=', 1) for v in vals):
            device[key] = val.strip()
        # Ignore block types not specified
        devtype = device.get('TYPE')

        # We already have devices, we should ensure we don't store duplicates.
        if _is_known_device(devices, device.get('KNAME')):
            continue

        # Search for raid in the reply type, as RAID is a
        # disk device, and we should honor it if is present.
        # Other possible type values, which we skip recording:
        #   lvm, part, rom, loop
        if devtype != block_type:
            if devtype is not None and 'raid' in devtype and not ignore_raid:
                LOG.debug(
                    "TYPE detected to contain 'raid', signifying a RAID "
                    "volume. Found: {!r}".format(line))
            else:
                LOG.debug(
                    "TYPE did not match. Wanted: {!r} but found: {!r}".format(
                        block_type, line))
                continue

        # Ensure all required columns are at least present, even if blank
        missing = set(columns) - set(device)
        if missing:
            raise errors.BlockDeviceError(
                '%s must be returned by lsblk.' % ', '.join(sorted(missing)))

        name = os.path.join('/dev', device['KNAME'])

        try:
            udev = pyudev.Device.from_device_file(context, name)
        # pyudev started raising another error in 0.18
        except (ValueError, EnvironmentError, pyudev.DeviceNotFoundError) as e:
            LOG.warning("Device %(dev)s is inaccessible, skipping... "
                        "Error: %(error)s", {'dev': name, 'error': e})
            extra = {}
        else:
            # TODO(lucasagomes): Since lsblk only supports
            # returning the short serial we are using
            # ID_SERIAL_SHORT here to keep compatibility with the
            # bash deploy ramdisk
            extra = {key: udev.get('ID_%s' % udev_key) for key, udev_key in
                     [('wwn', 'WWN'), ('serial', 'SERIAL_SHORT'),
                      ('wwn_with_extension', 'WWN_WITH_EXTENSION'),
                      ('wwn_vendor_extension', 'WWN_VENDOR_EXTENSION')]}

        # NOTE(lucasagomes): Newer versions of the lsblk tool supports
        # HCTL as a parameter but let's get it from sysfs to avoid breaking
        # old distros.
        try:
            extra['hctl'] = os.listdir(
                '/sys/block/%s/device/scsi_device' % device['KNAME'])[0]
        except (OSError, IndexError):
            LOG.warning('Could not find the SCSI address (HCTL) for '
                        'device %s. Skipping', name)

        # Not all /dev entries are pointed to from /dev/disk/by-path
        by_path_name = by_path_mapping.get(name)

        devices.append(BlockDevice(name=name,
                                   model=device['MODEL'],
                                   size=int(device['SIZE']),
                                   rotational=bool(int(device['ROTA'])),
                                   vendor=_get_device_info(device['KNAME'],
                                                           'block', 'vendor'),
                                   by_path=by_path_name,
                                   **extra))
    return devices


class HardwareSupport(object):
    """Example priorities for hardware managers.

    Priorities for HardwareManagers are integers, where largest means most
    specific and smallest means most generic. These values are guidelines
    that suggest values that might be returned by calls to
    `evaluate_hardware_support()`. No HardwareManager in mainline IPA will
    ever return a value greater than MAINLINE. Third party hardware managers
    should feel free to return values of SERVICE_PROVIDER or greater to
    distinguish between additional levels of hardware support.
    """
    NONE = 0
    GENERIC = 1
    MAINLINE = 2
    SERVICE_PROVIDER = 3


class HardwareType(object):
    MAC_ADDRESS = 'mac_address'


class BlockDevice(encoding.SerializableComparable):
    serializable_fields = ('name', 'model', 'size', 'rotational',
                           'wwn', 'serial', 'vendor', 'wwn_with_extension',
                           'wwn_vendor_extension', 'hctl', 'by_path')

    def __init__(self, name, model, size, rotational, wwn=None, serial=None,
                 vendor=None, wwn_with_extension=None,
                 wwn_vendor_extension=None, hctl=None, by_path=None):
        self.name = name
        self.model = model
        self.size = size
        self.rotational = rotational
        self.wwn = wwn
        self.serial = serial
        self.vendor = vendor
        self.wwn_with_extension = wwn_with_extension
        self.wwn_vendor_extension = wwn_vendor_extension
        self.hctl = hctl
        self.by_path = by_path


class NetworkInterface(encoding.SerializableComparable):
    serializable_fields = ('name', 'mac_address', 'ipv4_address',
                           'ipv6_address', 'has_carrier', 'lldp',
                           'vendor', 'product', 'client_id',
                           'biosdevname')

    def __init__(self, name, mac_addr, ipv4_address=None, ipv6_address=None,
                 has_carrier=True, lldp=None, vendor=None, product=None,
                 client_id=None, biosdevname=None):
        self.name = name
        self.mac_address = mac_addr
        self.ipv4_address = ipv4_address
        self.ipv6_address = ipv6_address
        self.has_carrier = has_carrier
        self.lldp = lldp
        self.vendor = vendor
        self.product = product
        self.biosdevname = biosdevname
        # client_id is used for InfiniBand only. we calculate the DHCP
        # client identifier Option to allow DHCP to work over InfiniBand.
        # see https://tools.ietf.org/html/rfc4390
        self.client_id = client_id


class CPU(encoding.SerializableComparable):
    serializable_fields = ('model_name', 'frequency', 'count', 'architecture',
                           'flags')

    def __init__(self, model_name, frequency, count, architecture,
                 flags=None):
        self.model_name = model_name
        self.frequency = frequency
        self.count = count
        self.architecture = architecture
        self.flags = flags or []


class Memory(encoding.SerializableComparable):
    serializable_fields = ('total', 'physical_mb')
    # physical = total + kernel binary + reserved space

    def __init__(self, total, physical_mb=None):
        self.total = total
        self.physical_mb = physical_mb


class SystemVendorInfo(encoding.SerializableComparable):
    serializable_fields = ('product_name', 'serial_number', 'manufacturer')

    def __init__(self, product_name, serial_number, manufacturer):
        self.product_name = product_name
        self.serial_number = serial_number
        self.manufacturer = manufacturer


class BootInfo(encoding.SerializableComparable):
    serializable_fields = ('current_boot_mode', 'pxe_interface')

    def __init__(self, current_boot_mode, pxe_interface=None):
        self.current_boot_mode = current_boot_mode
        self.pxe_interface = pxe_interface


@six.add_metaclass(abc.ABCMeta)
class HardwareManager(object):
    @abc.abstractmethod
    def evaluate_hardware_support(self):
        pass

    def list_network_interfaces(self):
        raise errors.IncompatibleHardwareMethodError

    def get_cpus(self):
        raise errors.IncompatibleHardwareMethodError

    def list_block_devices(self, include_partitions=False):
        """List physical block devices

        :param include_partitions: If to include partitions
        :return: A list of BlockDevices
        """
        raise errors.IncompatibleHardwareMethodError

    def get_memory(self):
        raise errors.IncompatibleHardwareMethodError

    def get_os_install_device(self):
        raise errors.IncompatibleHardwareMethodError

    def get_bmc_address(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_bmc_v6address(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_boot_info(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_interface_info(self, interface_name):
        raise errors.IncompatibleHardwareMethodError()

    def erase_block_device(self, node, block_device):
        """Attempt to erase a block device.

        Implementations should detect the type of device and erase it in the
        most appropriate way possible. Generic implementations should support
        common erase mechanisms such as ATA secure erase, or multi-pass random
        writes. Operators with more specific needs should override this method
        in order to detect and handle "interesting" cases, or delegate to the
        parent class to handle generic cases.

        For example: operators running ACME MagicStore (TM) cards alongside
        standard SSDs might check whether the device is a MagicStore and use a
        proprietary tool to erase that, otherwise call this method on their
        parent class. Upstream submissions of common functionality are
        encouraged.

        This interface could be called concurrently to speed up erasure, as
        such, it should be implemented in a thread-safe way.

        :param node: Ironic node object
        :param block_device: a BlockDevice indicating a device to be erased.
        :raises IncompatibleHardwareMethodError: when there is no known way to
                erase the block device
        :raises BlockDeviceEraseError: when there is an error erasing the
                block device
        """
        raise errors.IncompatibleHardwareMethodError

    def erase_devices(self, node, ports):
        """Erase any device that holds user data.

        By default this will attempt to erase block devices. This method can be
        overridden in an implementation-specific hardware manager in order to
        erase additional hardware, although backwards-compatible upstream
        submissions are encouraged.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :return: a dictionary in the form {device.name: erasure output}
        """
        erase_results = {}
        block_devices = self.list_block_devices()
        if not len(block_devices):
            return {}

        info = node.get('driver_internal_info', {})
        max_pool_size = info.get('disk_erasure_concurrency', 1)

        thread_pool = ThreadPool(min(max_pool_size, len(block_devices)))
        for block_device in block_devices:
            params = {'node': node, 'block_device': block_device}
            erase_results[block_device.name] = thread_pool.apply_async(
                dispatch_to_managers, ('erase_block_device',), params)
        thread_pool.close()
        thread_pool.join()

        for device_name, result in erase_results.items():
            erase_results[device_name] = result.get()

        return erase_results

    def wait_for_disks(self):
        """Wait for the root disk to appear.

        Wait for at least one suitable disk to show up or a specific disk
        if any device hint is specified. Otherwise neither inspection
        not deployment have any chances to succeed.

        """
        if not CONF.disk_wait_attempts:
            return

        max_waits = CONF.disk_wait_attempts - 1
        for attempt in range(CONF.disk_wait_attempts):
            try:
                self.get_os_install_device()
            except errors.DeviceNotFound:
                LOG.debug('Still waiting for the root device to appear, '
                          'attempt %d of %d', attempt + 1,
                          CONF.disk_wait_attempts)

                if attempt < max_waits:
                    time.sleep(CONF.disk_wait_delay)
            else:
                break
        else:
            if max_waits:
                LOG.warning('The root device was not detected in %d seconds',
                            CONF.disk_wait_delay * max_waits)
            else:
                LOG.warning('The root device was not detected')

    def list_hardware_info(self):
        """Return full hardware inventory as a serializable dict.

        This inventory is sent to Ironic on lookup and to Inspector on
        inspection.

        :return: a dictionary representing inventory
        """
        # NOTE(dtantsur): don't forget to update docs when extending inventory
        hardware_info = {}
        hardware_info['interfaces'] = self.list_network_interfaces()
        hardware_info['cpu'] = self.get_cpus()
        hardware_info['disks'] = self.list_block_devices()
        hardware_info['memory'] = self.get_memory()
        hardware_info['bmc_address'] = self.get_bmc_address()
        hardware_info['bmc_v6address'] = self.get_bmc_v6address()
        hardware_info['system_vendor'] = self.get_system_vendor_info()
        hardware_info['boot'] = self.get_boot_info()
        hardware_info['hostname'] = netutils.get_hostname()
        return hardware_info

    def get_clean_steps(self, node, ports):
        """Get a list of clean steps with priority.

        Returns a list of steps. Each step is represented by a dict::

          {
           'interface': the name of the driver interface that should execute
                        the step.
           'step': the HardwareManager function to call.
           'priority': the order steps will be run in. Ironic will sort all
                       the clean steps from all the drivers, with the largest
                       priority step being run first. If priority is set to 0,
                       the step will not be run during cleaning, but may be
                       run during zapping.
           'reboot_requested': Whether the agent should request Ironic reboots
                               the node via the power driver after the
                               operation completes.
           'abortable': Boolean value. Whether the clean step can be
                        stopped by the operator or not. Some clean step may
                        cause non-reversible damage to a machine if interrupted
                        (i.e firmware update), for such steps this parameter
                        should be set to False. If no value is set for this
                        parameter, Ironic will consider False (non-abortable).
          }


        If multiple hardware managers return the same step name, the following
        logic will be used to determine which manager's step "wins":

            * Keep the step that belongs to HardwareManager with highest
              HardwareSupport (larger int) value.
            * If equal support level, keep the step with the higher defined
              priority (larger int).
            * If equal support level and priority, keep the step associated
              with the HardwareManager whose name comes earlier in the
              alphabet.

        The steps will be called using `hardware.dispatch_to_managers` and
        handled by the best suited hardware manager. If you need a step to be
        executed by only your hardware manager, ensure it has a unique step
        name.

        `node` and `ports` can be used by other hardware managers to further
        determine if a clean step is supported for the node.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :return: a list of cleaning steps, where each step is described as a
                 dict as defined above

        """
        return []

    def get_version(self):
        """Get a name and version for this hardware manager.

        In order to avoid errors and make agent upgrades painless, cleaning
        will check the version of all hardware managers during get_clean_steps
        at the beginning of cleaning and before executing each step in the
        agent.

        The agent isn't aware of the steps being taken before or after via
        out of band steps, so it can never know if a new step is safe to run.
        Therefore, we default to restarting the whole process.

        :returns: a dictionary with two keys: `name` and
            `version`, where `name` is a string identifying the hardware
            manager and `version` is an arbitrary version string. `name` will
            be a class variable called HARDWARE_MANAGER_NAME, or default to
            the class name and `version` will be a class variable called
            HARDWARE_MANAGER_VERSION or default to '1.0'.
        """
        return {
            'name': getattr(self, 'HARDWARE_MANAGER_NAME',
                            type(self).__name__),
            'version': getattr(self, 'HARDWARE_MANAGER_VERSION', '1.0')
        }


class GenericHardwareManager(HardwareManager):
    HARDWARE_MANAGER_NAME = 'generic_hardware_manager'
    # 1.1 - Added new clean step called erase_devices_metadata
    HARDWARE_MANAGER_VERSION = '1.1'

    def __init__(self):
        self.sys_path = '/sys'
        self.lldp_data = {}

    def evaluate_hardware_support(self):
        # Do some initialization before we declare ourself ready
        _check_for_iscsi()
        self.wait_for_disks()
        return HardwareSupport.GENERIC

    def collect_lldp_data(self, interface_names):
        """Collect and convert LLDP info from the node.

        In order to process the LLDP information later, the raw data needs to
        be converted for serialization purposes.

        :param interface_names: list of names of node's interfaces.
        :return: a dict, containing the lldp data from every interface.
        """

        interface_names = [name for name in interface_names if name != 'lo']
        lldp_data = {}
        try:
            raw_lldp_data = netutils.get_lldp_info(interface_names)
        except Exception:
            # NOTE(sambetts) The get_lldp_info function will log this exception
            # and we don't invalidate any existing data in the cache if we fail
            # to get data to replace it so just return.
            return lldp_data
        for ifname, tlvs in raw_lldp_data.items():
            # NOTE(sambetts) Convert each type-length-value (TLV) value to hex
            # so that it can be serialised safely
            processed_tlvs = []
            for typ, data in tlvs:
                try:
                    processed_tlvs.append((typ,
                                           binascii.hexlify(data).decode()))
                except (binascii.Error, binascii.Incomplete) as e:
                    LOG.warning('An error occurred while processing TLV type '
                                '%s for interface %s: %s', (typ, ifname, e))
            lldp_data[ifname] = processed_tlvs
        return lldp_data

    def _get_lldp_data(self, interface_name):
        if self.lldp_data:
            return self.lldp_data.get(interface_name)

    def get_interface_info(self, interface_name):

        mac_addr = netutils.get_mac_addr(interface_name)
        if mac_addr is None:
            raise errors.IncompatibleHardwareMethodError()

        return NetworkInterface(
            interface_name, mac_addr,
            ipv4_address=self.get_ipv4_addr(interface_name),
            ipv6_address=self.get_ipv6_addr(interface_name),
            has_carrier=netutils.interface_has_carrier(interface_name),
            vendor=_get_device_info(interface_name, 'net', 'vendor'),
            product=_get_device_info(interface_name, 'net', 'device'),
            biosdevname=self.get_bios_given_nic_name(interface_name))

    def get_ipv4_addr(self, interface_id):
        return netutils.get_ipv4_addr(interface_id)

    def get_ipv6_addr(self, interface_id):
        """Get the default IPv6 address assigned to the interface.

        With different networking environment, the address could be a
        link-local address, ULA or something else.
        """
        return netutils.get_ipv6_addr(interface_id)

    def get_bios_given_nic_name(self, interface_name):
        """Collect the BIOS given NICs name.

        This function uses the biosdevname utility to collect the BIOS given
        name of network interfaces.

        The collected data is added to the network interface inventory with an
        extra field named ``biosdevname``.

        :param interface_name: list of names of node's interfaces.
        :return: the BIOS given NIC name of node's interfaces or default
                 as None.
        """
        global WARN_BIOSDEVNAME_NOT_FOUND
        try:
            stdout, _ = utils.execute('biosdevname', '-i',
                                      interface_name)
            return stdout.rstrip('\n')
        except OSError:
            if not WARN_BIOSDEVNAME_NOT_FOUND:
                LOG.warning("Executable 'biosdevname' not found")
                WARN_BIOSDEVNAME_NOT_FOUND = True
        except processutils.ProcessExecutionError as e:
            # NOTE(alezil) biosdevname returns 4 if running in a
            # virtual machine.
            if e.exit_code == 4:
                LOG.info('The system is a virtual machine, so biosdevname '
                         'utility does not provide names for virtual NICs.')
            else:
                LOG.warning('Biosdevname returned exit code %s', e.exit_code)

    def _is_device(self, interface_name):
        device_path = '{}/class/net/{}/device'.format(self.sys_path,
                                                      interface_name)
        return os.path.exists(device_path)

    def list_network_interfaces(self):
        network_interfaces_list = []
        iface_names = os.listdir('{}/class/net'.format(self.sys_path))
        iface_names = [name for name in iface_names if self._is_device(name)]

        if CONF.collect_lldp:
            self.lldp_data = dispatch_to_managers('collect_lldp_data',
                                                  interface_names=iface_names)

        for iface_name in iface_names:
            result = dispatch_to_managers(
                'get_interface_info', interface_name=iface_name)
            result.lldp = self._get_lldp_data(iface_name)
            network_interfaces_list.append(result)

        return network_interfaces_list

    def get_cpus(self):
        lines = utils.execute('lscpu')[0]
        cpu_info = {k.strip().lower(): v.strip() for k, v in
                    (line.split(':', 1)
                     for line in lines.split('\n')
                     if line.strip())}
        # Current CPU frequency can be different from maximum one on modern
        # processors
        freq = cpu_info.get('cpu max mhz', cpu_info.get('cpu mhz'))

        flags = []
        out = utils.try_execute('grep', '-Em1', '^flags', '/proc/cpuinfo')
        if out:
            try:
                # Example output (much longer for a real system):
                # flags           : fpu vme de pse
                flags = out[0].strip().split(':', 1)[1].strip().split()
            except (IndexError, ValueError):
                LOG.warning('Malformed CPU flags information: %s', out)
        else:
            LOG.warning('Failed to get CPU flags')

        return CPU(model_name=cpu_info.get('model name'),
                   frequency=freq,
                   # this includes hyperthreading cores
                   count=int(cpu_info.get('cpu(s)')),
                   architecture=cpu_info.get('architecture'),
                   flags=flags)

    def get_memory(self):
        # psutil returns a long, so we force it to an int
        try:
            total = int(psutil.virtual_memory().total)
        except Exception:
            # This is explicitly catching all exceptions. We want to catch any
            # situation where a newly upgraded psutil would fail, and instead
            # print an error instead of blowing up the stack on IPA.
            total = None
            LOG.exception(("Cannot fetch total memory size using psutil "
                           "version %s"), psutil.version_info[0])
        sys_dict = None
        try:
            sys_dict = _get_system_lshw_dict()
        except (processutils.ProcessExecutionError, OSError, ValueError) as e:
            LOG.warning('Could not get real physical RAM from lshw: %s', e)
            physical = None
        else:
            physical = 0
            # locate memory information in system_dict
            for sys_child in sys_dict['children']:
                if sys_child['id'] == 'core':
                    for core_child in sys_child['children']:
                        if _MEMORY_ID_RE.match(core_child['id']):
                            for bank in core_child.get('children', ()):
                                if bank.get('size'):
                                    value = ("%(size)s %(units)s" % bank)
                                    physical += int(UNIT_CONVERTER(value).to
                                                    ('MB').magnitude)

            if not physical:
                LOG.warning('Did not find any physical RAM')

        return Memory(total=total, physical_mb=physical)

    def list_block_devices(self, include_partitions=False):
        block_devices = list_all_block_devices()
        if include_partitions:
            block_devices.extend(
                list_all_block_devices(block_type='part',
                                       ignore_raid=True)
            )
        return block_devices

    def get_os_install_device(self):
        cached_node = get_cached_node()
        root_device_hints = None
        if cached_node is not None:
            root_device_hints = cached_node['properties'].get('root_device')
            LOG.debug('Looking for a device matching root hints %s',
                      root_device_hints)

        block_devices = self.list_block_devices()
        if not root_device_hints:
            dev_name = utils.guess_root_disk(block_devices).name
        else:
            serialized_devs = [dev.serialize() for dev in block_devices]
            try:
                device = il_utils.match_root_device_hints(serialized_devs,
                                                          root_device_hints)
            except ValueError as e:
                # NOTE(lucasagomes): Just playing on the safe side
                # here, this exception should never be raised because
                # Ironic should validate the root device hints before the
                # deployment starts.
                raise errors.DeviceNotFound(
                    'No devices could be found using the root device hints '
                    '%(hints)s because they failed to validate. Error: '
                    '%(error)s' % {'hints': root_device_hints, 'error': e})

            if not device:
                raise errors.DeviceNotFound(
                    "No suitable device was found for "
                    "deployment using these hints %s" % root_device_hints)

            dev_name = device['name']

        LOG.info('Picked root device %(dev)s for node %(node)s based on '
                 'root device hints %(hints)s',
                 {'dev': dev_name, 'hints': root_device_hints,
                  'node': cached_node['uuid'] if cached_node else None})
        return dev_name

    def get_system_vendor_info(self):
        try:
            sys_dict = _get_system_lshw_dict()
        except (processutils.ProcessExecutionError, OSError, ValueError) as e:
            #LOG.warning('Could not retrieve vendor info from lshw: %e', e)
            LOG.warning('TAL WAS HERE')
            sys_dict = {}
        return SystemVendorInfo(product_name=sys_dict.get('product', ''),
                                serial_number=sys_dict.get('serial', ''),
                                manufacturer=sys_dict.get('vendor', ''))

    def get_boot_info(self):
        boot_mode = 'uefi' if os.path.isdir('/sys/firmware/efi') else 'bios'
        LOG.debug('The current boot mode is %s', boot_mode)
        pxe_interface = utils.get_agent_params().get('BOOTIF')
        return BootInfo(current_boot_mode=boot_mode,
                        pxe_interface=pxe_interface)

    def erase_block_device(self, node, block_device):
        # Check if the block device is virtual media and skip the device.
        if self._is_virtual_media_device(block_device):
            LOG.info("Skipping erase of virtual media device %s",
                     block_device.name)
            return
        if self._is_linux_raid_member(block_device):
            LOG.info("Skipping erase of RAID member device %s",
                     block_device.name)
            return
        info = node.get('driver_internal_info', {})
        # Note(TheJulia) Use try/except to capture and log the failure
        # and then revert to attempting to shred the volume if enabled.
        try:
            execute_secure_erase = info.get(
                'agent_enable_ata_secure_erase', True)
            if execute_secure_erase and self._ata_erase(block_device):
                return
        except errors.BlockDeviceEraseError as e:
            execute_shred = info.get(
                'agent_continue_if_ata_erase_failed', False)
            if execute_shred:
                LOG.warning('Failed to invoke ata_erase, '
                            'falling back to shred: %(err)s',
                            {'err': e})
            else:
                msg = ('Failed to invoke ata_erase, '
                       'fallback to shred is not enabled: %(err)s'
                       % {'err': e})
                LOG.error(msg)
                raise errors.IncompatibleHardwareMethodError(msg)

        if self._shred_block_device(node, block_device):
            return

        msg = ('Unable to erase block device {}: device is unsupported.'
               ).format(block_device.name)
        LOG.error(msg)
        raise errors.IncompatibleHardwareMethodError(msg)

    def erase_devices_metadata(self, node, ports):
        """Attempt to erase the disk devices metadata.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :raises BlockDeviceEraseError: when there's an error erasing the
                block device
        """
        block_devices = self.list_block_devices(include_partitions=True)
        # NOTE(coreywright): Reverse sort by device name so a partition (eg
        # sda1) is processed before it disappears when its associated disk (eg
        # sda) has its partition table erased and the kernel notified.
        block_devices.sort(key=lambda dev: dev.name, reverse=True)
        erase_errors = {}
        for dev in block_devices:
            if self._is_virtual_media_device(dev):
                LOG.info("Skipping metadata erase of virtual media device %s",
                         dev.name)
                continue
            if self._is_linux_raid_member(dev):
                LOG.info("Skipping metadata erase of RAID member device %s",
                         dev.name)
                continue

            try:
                disk_utils.destroy_disk_metadata(dev.name, node['uuid'])
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to erase the metadata on device "%(dev)s". '
                          'Error: %(error)s', {'dev': dev.name, 'error': e})
                erase_errors[dev.name] = e

        if erase_errors:
            excpt_msg = ('Failed to erase the metadata on the device(s): %s' %
                         '; '.join(['"%s": %s' % (k, v)
                                    for k, v in erase_errors.items()]))
            raise errors.BlockDeviceEraseError(excpt_msg)

    def _shred_block_device(self, node, block_device):
        """Erase a block device using shred.

        :param node: Ironic node info.
        :param block_device: a BlockDevice object to be erased
        :returns: True if the erase succeeds, False if it fails for any reason
        """
        info = node.get('driver_internal_info', {})
        npasses = info.get('agent_erase_devices_iterations', 1)
        args = ('shred', '--force')

        if info.get('agent_erase_devices_zeroize', True):
            args += ('--zero', )

        args += ('--verbose', '--iterations', str(npasses), block_device.name)

        try:
            utils.execute(*args)
        except (processutils.ProcessExecutionError, OSError) as e:
            msg = "Erasing block device %(dev)s failed with error %(err)s"
            LOG.error(msg, {'dev': block_device.name, 'err': e})
            return False

        return True

    def _is_virtual_media_device(self, block_device):
        """Check if the block device corresponds to Virtual Media device.

        :param block_device: a BlockDevice object
        :returns: True if it's a virtual media device, else False
        """
        vm_device_label = '/dev/disk/by-label/ir-vfd-dev'
        if os.path.exists(vm_device_label):
            link = os.readlink(vm_device_label)
            device = os.path.normpath(os.path.join(os.path.dirname(
                                                   vm_device_label), link))
            if block_device.name == device:
                return True
        return False

    def _is_linux_raid_member(self, block_device):
        """Check if a block device is a Linux RAID member.

        :param block_device: a BlockDevice object
        :returns: True if it's Linux RAID member (or if we do not
                  manage to verify), False otherwise.
        """
        try:
            # Don't use the '--nodeps' of lsblk to also catch the
            # parent device of partitions which are RAID members.
            out, _ = utils.execute('lsblk', '--fs', '--noheadings',
                                   block_device.name)
        except processutils.ProcessExecutionError as e:
            LOG.warning("Could not determine if %s is a RAID member: %s",
                        block_device.name, e)
            return True

        return 'linux_raid_member' in out

    def _get_ata_security_lines(self, block_device):
        output = utils.execute('hdparm', '-I', block_device.name)[0]

        if '\nSecurity: ' not in output:
            return []

        # Get all lines after the 'Security: ' line
        security_and_beyond = output.split('\nSecurity: \n')[1]
        security_and_beyond_lines = security_and_beyond.split('\n')

        security_lines = []
        for line in security_and_beyond_lines:
            if line.startswith('\t'):
                security_lines.append(line.strip().replace('\t', ' '))
            else:
                break

        return security_lines

    def _smartctl_security_check(self, block_device):
        """Checks if we can query security via smartctl.

            :param block_device: A block_device object

            :returns: True if we can query the block device via ATA
                      or the smartctl binary is not present.
                      False if we cannot query the device.
        """
        try:
            # NOTE(TheJulia): smartctl has a concept of drivers being how
            # to query or interpret data from the device. We want to use `ata`
            # instead of `scsi` or `sat` as smartctl will not be able to read
            # a bridged device that it doesn't understand, and accordingly
            # return an error code.
            output = utils.execute('smartctl', '-d', 'ata', block_device.name,
                                   '-g', 'security',
                                   check_exit_code=[0, 127])[0]
            if 'Unavailable' in output:
                # Smartctl is reporting it is unavailable, lets return false.
                LOG.debug('Smartctl has reported that security is '
                          'unavailable on device %s.', block_device.name)
                return False
            return True
        except processutils.ProcessExecutionError:
            # Things don't look so good....
            LOG.warning('Refusing to permit ATA Secure Erase as direct '
                        'ATA commands via the `smartctl` utility with device '
                        '%s do not succeed.', block_device.name)
            return False
        except OSError:
            # Processutils can raise OSError if a path is not found,
            # and it is okay that we tollerate that since it was the
            # prior behavior.
            return True

    def _ata_erase(self, block_device):

        def __attempt_unlock_drive(block_device, security_lines=None):
            # Attempt to unlock the drive in the event it has already been
            # locked by a previous failed attempt. We try the empty string as
            # versions of hdparm < 9.51, interpreted NULL as the literal
            # string, "NULL", as opposed to the empty string.
            if not security_lines:
                security_lines = self._get_ata_security_lines(block_device)
            unlock_passwords = ['NULL', '']
            for password in unlock_passwords:
                if 'not locked' in security_lines:
                    break
                try:
                    utils.execute('hdparm', '--user-master', 'u',
                                  '--security-unlock', password,
                                  block_device.name)
                except processutils.ProcessExecutionError as e:
                    LOG.info('Security unlock failed for device '
                             '%(name)s using password "%(password)s": %(err)s',
                             {'name': block_device.name,
                              'password': password,
                              'err': e})
                security_lines = self._get_ata_security_lines(block_device)
            return security_lines

        security_lines = self._get_ata_security_lines(block_device)

        # If secure erase isn't supported return False so erase_block_device
        # can try another mechanism. Below here, if secure erase is supported
        # but fails in some way, error out (operators of hardware that supports
        # secure erase presumably expect this to work).
        if (not self._smartctl_security_check(block_device)
                or 'supported' not in security_lines):
            return False

        # At this point, we could be SEC1,2,4,5,6

        if 'not frozen' not in security_lines:
            # In SEC2 or 6
            raise errors.BlockDeviceEraseError(
                ('Block device {} is frozen and cannot be erased'
                 ).format(block_device.name))

        # At this point, we could be in SEC1,4,5
        # Attempt to unlock the drive if it has failed in a prior attempt.
        security_lines = __attempt_unlock_drive(block_device, security_lines)

        # If the unlock failed we will still be in SEC4, otherwise, we will be
        # in SEC1 or SEC5

        if 'not locked' not in security_lines:
            # In SEC4
            raise errors.BlockDeviceEraseError(
                ('Block device {} already has a security password set'
                 ).format(block_device.name))

        # At this point, we could be in SEC1 or 5
        if 'not enabled' in security_lines:
            # SEC1. Try to transition to SEC5 by setting empty user
            # password.
            try:
                utils.execute('hdparm', '--user-master', 'u',
                              '--security-set-pass', 'NULL', block_device.name)
            except processutils.ProcessExecutionError as e:
                error_msg = ('Security password set failed for device '
                             '{name}: {err}'
                             ).format(name=block_device.name, err=e)
                raise errors.BlockDeviceEraseError(error_msg)

        # Use the 'enhanced' security erase option if it's supported.
        erase_option = '--security-erase'
        if 'not supported: enhanced erase' not in security_lines:
            erase_option += '-enhanced'

        try:
            utils.execute('hdparm', '--user-master', 'u', erase_option,
                          'NULL', block_device.name)
        except processutils.ProcessExecutionError as e:
            # NOTE(TheJulia): Attempt unlock to allow fallback to shred
            # to occur, otherwise shred will fail as well, as the security
            # mode will prevent IO operations to the disk.
            __attempt_unlock_drive(block_device)
            raise errors.BlockDeviceEraseError('Erase failed for device '
                                               '%(name)s: %(err)s' %
                                               {'name': block_device.name,
                                                'err': e})

        # Verify that security is now 'not enabled'
        security_lines = self._get_ata_security_lines(block_device)
        if 'not enabled' not in security_lines:
            # Not SEC1 - fail
            raise errors.BlockDeviceEraseError(
                ('An unknown error occurred erasing block device {}'
                 ).format(block_device.name))

        # In SEC1 security state
        return True

    def get_bmc_address(self):
        """Attempt to detect BMC IP address

        :return: IP address of lan channel or 0.0.0.0 in case none of them is
                 configured properly
        """
        # These modules are rarely loaded automatically
        utils.try_execute('modprobe', 'ipmi_msghandler')
        utils.try_execute('modprobe', 'ipmi_devintf')
        utils.try_execute('modprobe', 'ipmi_si')

        try:
            # From all the channels 0-15, only 1-11 can be assigned to
            # different types of communication media and protocols and
            # effectively used
            for channel in range(1, 12):
                out, e = utils.execute(
                    "ipmitool lan print {} | awk '/IP Address[ \\t]*:/"
                    " {{print $4}}'".format(channel), shell=True)
                if e.startswith("Invalid channel"):
                    continue
                out = out.strip()

                try:
                    netaddr.IPAddress(out)
                except netaddr.AddrFormatError:
                    LOG.warning('Invalid IP address: %s', out)
                    continue

                # In case we get 0.0.0.0 on a valid channel, we need to keep
                # querying
                if out != '0.0.0.0':
                    return out

        except (processutils.ProcessExecutionError, OSError) as e:
            # Not error, because it's normal in virtual environment
            LOG.warning("Cannot get BMC address: %s", e)
            return

        return '0.0.0.0'

    def get_bmc_v6address(self):
        """Attempt to detect BMC v6 address

        :return: IPv6 address of lan channel or ::/0 in case none of them is
                 configured properly. May return None value if it cannot
                 interract with system tools or critical error occurs.
        """
        # These modules are rarely loaded automatically
        utils.try_execute('modprobe', 'ipmi_msghandler')
        utils.try_execute('modprobe', 'ipmi_devintf')
        utils.try_execute('modprobe', 'ipmi_si')

        null_address_re = re.compile(r'^::(/\d{1,3})*$')

        def get_addr(channel, dynamic=False):
            cmd = "ipmitool lan6 print {} {}_addr".format(
                channel, 'dynamic' if dynamic else 'static')
            try:
                out, e = utils.execute(cmd, shell=True)
            except processutils.ProcessExecutionError:
                return

            # NOTE: More likely ipmitool was not intended to return
            #       stdout in yaml format. Fortunately, output of
            #       dynamic_addr and static_addr commands is a valid yaml.
            try:
                out = yaml.safe_load(out.strip())
            except yaml.YAMLError as e:
                LOG.warning('Cannot process output of "%(cmd)s" '
                            'command: %(e)s', {'cmd': cmd, 'e': e})
                return

            for addr_dict in out.values():
                address = addr_dict['Address']
                if dynamic:
                    enabled = addr_dict['Source/Type'] in ['DHCPv6', 'SLAAC']
                else:
                    enabled = addr_dict['Enabled']

                if addr_dict['Status'] == 'active' and enabled \
                        and not null_address_re.match(address):
                    return address

        try:
            # From all the channels 0-15, only 1-11 can be assigned to
            # different types of communication media and protocols and
            # effectively used
            for channel in range(1, 12):
                addr_mode, e = utils.execute(
                    r"ipmitool lan6 print {} enables | "
                    r"awk '/IPv6\/IPv4 Addressing Enables[ \t]*:/"
                    r"{{print $NF}}'".format(channel), shell=True)
                if addr_mode.strip() not in ['ipv6', 'both']:
                    continue

                address = get_addr(channel, dynamic=True) or get_addr(channel)
                if not address:
                    continue

                try:
                    return str(netaddr.IPNetwork(address).ip)
                except netaddr.AddrFormatError:
                    LOG.warning('Invalid IP address: %s', address)
                    continue
        except (processutils.ProcessExecutionError, OSError) as e:
            # Not error, because it's normal in virtual environment
            LOG.warning("Cannot get BMC v6 address: %s", e)
            return

        return '::/0'

    def get_clean_steps(self, node, ports):
        return [
            {
                'step': 'erase_devices',
                'priority': 10,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_metadata',
                'priority': 99,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'delete_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'create_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            }
        ]

    def create_configuration(self, node, ports):
        """Create a RAID configuration.

        Unless overwritten by a local hardware manager, this method
        will create a software RAID configuration as read from the
        node's 'target_raid_config'.

        :param node: A dictionary of the node object.
        :param ports: A list of dictionaries containing information
                      of ports for the node.
        :returns: The current RAID configuration in the usual format.
        :raises: SoftwareRAIDError if the desired configuration is not
                 valid or if there was an error when creating the RAID
                 devices.
        """

        raid_config = node.get('target_raid_config', {})

        # No 'software' controller: do nothing. If 'controller' is
        # set to 'software' on only one of the drives, the validation
        # code will catch it.
        software_raid = False
        logical_disks = raid_config.get('logical_disks')
        for logical_disk in logical_disks:
            if logical_disk.get('controller') == 'software':
                software_raid = True
                break
        if not software_raid:
            LOG.debug("No Software RAID config found")
            return {}

        LOG.info("Creating Software RAID")

        # Check if the config is compliant with current limitations.
        self.validate_configuration(raid_config, node)

        # Log the validated target_raid_configuration.
        LOG.debug("Target Software RAID configuration: %s", raid_config)

        # Make sure there are no partitions yet (or left behind).
        block_devices = self.list_block_devices()
        block_devices_partitions = self.list_block_devices(
            include_partitions=True)
        if len(block_devices) != len(block_devices_partitions):
            partitions = ' '.join(
                partition.name for partition in block_devices_partitions)
            msg = "Partitions detected during RAID config: {}". format(
                  partitions)
            raise errors.SoftwareRAIDError(msg)

        # Create an MBR partition table on each disk.
        # TODO(arne_wiebalck): Check if GPT would work as well.
        for block_device in block_devices:
            LOG.info("Creating partition table on {}".format(
                block_device.name))
            try:
                utils.execute('parted', block_device.name, '-s', '--',
                              'mklabel', 'msdos')
            except processutils.ProcessExecutionError as e:
                msg = "Failed to create partition table on {}: {}".format(
                    block_device.name, e)
                raise errors.SoftwareRAIDError(msg)

        # Create the partitions which will become the component devices.
        sector = '2048s'
        for logical_disk in logical_disks:
            psize = logical_disk['size_gb']
            if psize == 'MAX':
                psize = '-1'
            else:
                psize = int(psize) * 1024
            for device in block_devices:
                try:
                    LOG.debug("Creating partition on {}: {} {}".format(
                        device.name, sector, psize))
                    utils.execute('parted', device.name, '-s', '-a',
                                  'optimal', '--', 'mkpart', 'primary',
                                  sector, psize)
                except processutils.ProcessExecutionError as e:
                    msg = "Failed to create partitions on {}: {}".format(
                        device.name, e)
                    raise errors.SoftwareRAIDError(msg)
            sector = psize

        # Create the RAID devices.
        raid_device_count = len(block_devices)
        for index, logical_disk in enumerate(logical_disks):
            md_device = '/dev/md%d' % index
            component_devices = [device.name + str(index + 1)
                                 for device in block_devices]
            raid_level = logical_disk['raid_level']
            # The schema check allows '1+0', but mdadm knows it as '10'.
            if raid_level == '1+0':
                raid_level = '10'
            try:
                LOG.debug("Creating md device {} on {}".format(
                          md_device, component_devices))
                utils.execute('mdadm', '--create', md_device, '--force',
                              '--run', '--metadata=1', '--level', raid_level,
                              '--raid-devices', raid_device_count,
                              *component_devices)
            except processutils.ProcessExecutionError as e:
                msg = "Failed to create md device {} on {}: {}".format(
                    md_device, ' '.join(component_devices), e)
                raise errors.SoftwareRAIDError(msg)

        LOG.info("Successfully created Software RAID")

        return raid_config

    def delete_configuration(self, node, ports):
        """Delete a RAID configuration.

        Unless overwritten by a local hardware manager, this method
        will delete all software RAID devices on the node.
        NOTE(arne_wiebalck): It may be worth considering to only
        delete RAID devices in the node's 'target_raid_config'. If
        that config has been lost, though, the cleanup may become
        difficult. So, for now, we delete everything we detect.

        :param node: A dictionary of the node object
        :param ports: A list of dictionaries containing information
                      of ports for the node
        """

        raid_devices = list_all_block_devices(block_type='raid',
                                              ignore_raid=False)
        for raid_device in raid_devices:
            LOG.info("Deleting Software RAID device {}".format(
                     raid_device.name))

            component_devices = _get_component_devices(raid_device.name)
            LOG.debug('Found component devices %s', component_devices)
            holder_disks = get_holder_disks(raid_device.name)
            LOG.debug('Found holder disks %s', holder_disks)

            # Remove md devices.
            try:
                utils.execute('wipefs', '-af', raid_device.name)
            except processutils.ProcessExecutionError as e:
                LOG.warning('Failed to wipefs %s: %s',
                            raid_device.name, e)
            try:
                utils.execute('mdadm', '--stop', raid_device.name)
            except processutils.ProcessExecutionError as e:
                LOG.warning('Failed to stop %s: %s',
                            raid_device.name, e)

            # Remove md metadata from component devices.
            for component_device in component_devices:
                try:
                    utils.execute('mdadm', '--examine', component_device,
                                  use_standard_locale=True)
                except processutils.ProcessExecutionError as e:
                    if "No md superblock detected" in str(e):
                        # actually not a component device
                        continue
                    else:
                        msg = "Failed to examine device {}: {}".format(
                              component_device, e)
                        raise errors.SoftwareRAIDError(msg)

                LOG.debug('Deleting md superblock on %s', component_device)
                try:
                    utils.execute('mdadm', '--zero-superblock',
                                  component_device)
                except processutils.ProcessExecutionError as e:
                    LOG.warning('Failed to remove superblock from %s: %s',
                                raid_device.name, e)

            # Remove the partitions we created during create_configuration.
            for holder_disk in holder_disks:
                LOG.debug('Removing partitions on %s', holder_disk)
                try:
                    utils.execute('wipefs', '-af', holder_disk)
                except processutils.ProcessExecutionError as e:
                    LOG.warning('Failed to remove partitions on %s',
                                holder_disk)

            LOG.info('Deleted Software RAID device %s', raid_device.name)

        LOG.debug("Finished deleting Software RAID(s)")

    def validate_configuration(self, raid_config, node):
        """Validate a (software) RAID configuration

        Validate a given raid_config, in particular with respect to
        the limitations of the current implementation of software
        RAID support.

        :param raid_config: The current RAID configuration in the usual format.
        """
        LOG.debug("Validating Software RAID config: {}".format(raid_config))

        if not raid_config:
            LOG.error("No RAID config passed")
            return False

        logical_disks = raid_config.get('logical_disks')
        if not logical_disks:
            msg = "RAID config contains no logical disks"
            raise errors.SoftwareRAIDError(msg)

        raid_errors = []

        # Only one or two RAID devices are supported for now.
        if len(logical_disks) not in [1, 2]:
            msg = ("Software RAID configuration requires one or "
                   "two logical disks")
            raid_errors.append(msg)

        # All disks need to be flagged for Software RAID
        for logical_disk in logical_disks:
            if logical_disk.get('controller') != 'software':
                msg = ("Software RAID configuration requires all logical "
                       "disks to have 'controller'='software'")
                raid_errors.append(msg)

        # The first RAID device needs to be RAID-1.
        if logical_disks[0]['raid_level'] != '1':
            msg = ("Software RAID Configuration requires RAID-1 for the "
                   "first logical disk")
            raid_errors.append(msg)

        # Additional checks when we have two RAID devices.
        if len(logical_disks) == 2:
            size1 = logical_disks[0]['size_gb']
            size2 = logical_disks[1]['size_gb']

            # Only one logical disk is allowed to span the whole device.
            if size1 == 'MAX' and size2 == 'MAX':
                msg = ("Software RAID can have only one RAID device with "
                       "size 'MAX'")
                raid_errors.append(msg)

            # Check the accepted RAID levels.
            current_level = logical_disks[1]['raid_level']
            if current_level not in SUPPORTED_SOFTWARE_RAID_LEVELS:
                msg = ("Software RAID configuration does not support "
                       "RAID level %s" % current_level)
                raid_errors.append(msg)

        if raid_errors:
            error = ('Could not validate Software RAID config for %(node)s: '
                     '%(errors)s') % {'node': node['uuid'],
                                      'errors': '; '.join(raid_errors)}
            raise errors.SoftwareRAIDError(error)


def _compare_extensions(ext1, ext2):
    mgr1 = ext1.obj
    mgr2 = ext2.obj
    return mgr2.evaluate_hardware_support() - mgr1.evaluate_hardware_support()


def _get_managers():
    """Get a list of hardware managers in priority order.

    Use stevedore to find all eligible hardware managers, sort them based on
    self-reported (via evaluate_hardware_support()) priorities, and return them
    in a list. The resulting list is cached in _global_managers.

    :returns: Priority-sorted list of hardware managers
    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    global _global_managers

    if not _global_managers:
        extension_manager = stevedore.ExtensionManager(
            namespace='ironic_python_agent.hardware_managers',
            invoke_on_load=True)

        # There will always be at least one extension available (the
        # GenericHardwareManager).
        if six.PY2:
            extensions = sorted(extension_manager, _compare_extensions)
        else:
            extensions = sorted(extension_manager,
                                key=functools.cmp_to_key(_compare_extensions))

        preferred_managers = []

        for extension in extensions:
            if extension.obj.evaluate_hardware_support() > 0:
                preferred_managers.append(extension.obj)
                LOG.info('Hardware manager found: {}'.format(
                    extension.entry_point_target))

        if not preferred_managers:
            raise errors.HardwareManagerNotFound

        _global_managers = preferred_managers

    return _global_managers


def dispatch_to_all_managers(method, *args, **kwargs):
    """Dispatch a method to all hardware managers.

    Dispatches the given method in priority order as sorted by
    `_get_managers`. If the method doesn't exist or raises
    IncompatibleHardwareMethodError, it continues to the next hardware manager.
    All managers that have hardware support for this node will be called,
    and their responses will be added to a dictionary of the form
    {HardwareManagerClassName: response}.

    :param method: hardware manager method to dispatch
    :param args: arguments to dispatched method
    :param kwargs: keyword arguments to dispatched method
    :raises errors.HardwareManagerMethodNotFound: if all managers raise
        IncompatibleHardwareMethodError.
    :returns: a dictionary with keys for each hardware manager that returns
        a response and the value as a list of results from that hardware
        manager.
    """
    responses = {}
    managers = _get_managers()
    for manager in managers:
        if getattr(manager, method, None):
            try:
                response = getattr(manager, method)(*args, **kwargs)
            except errors.IncompatibleHardwareMethodError:
                LOG.debug('HardwareManager {} does not support {}'
                          .format(manager, method))
                continue
            except Exception as e:
                LOG.exception('Unexpected error dispatching %(method)s to '
                              'manager %(manager)s: %(e)s',
                              {'method': method, 'manager': manager, 'e': e})
                raise
            responses[manager.__class__.__name__] = response
        else:
            LOG.debug('HardwareManager {} does not have method {}'
                      .format(manager, method))

    if responses == {}:
        raise errors.HardwareManagerMethodNotFound(method)

    return responses


def dispatch_to_managers(method, *args, **kwargs):
    """Dispatch a method to best suited hardware manager.

    Dispatches the given method in priority order as sorted by
    `_get_managers`. If the method doesn't exist or raises
    IncompatibleHardwareMethodError, it is attempted again with a more generic
    hardware manager. This continues until a method executes that returns
    any result without raising an IncompatibleHardwareMethodError.

    :param method: hardware manager method to dispatch
    :param args: arguments to dispatched method
    :param kwargs: keyword arguments to dispatched method

    :returns: result of successful dispatch of method
    :raises HardwareManagerMethodNotFound: if all managers failed the method
    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    managers = _get_managers()
    for manager in managers:
        if getattr(manager, method, None):
            try:
                return getattr(manager, method)(*args, **kwargs)
            except(errors.IncompatibleHardwareMethodError):
                LOG.debug('HardwareManager {} does not support {}'
                          .format(manager, method))
            except Exception as e:
                LOG.exception('Unexpected error dispatching %(method)s to '
                              'manager %(manager)s: %(e)s',
                              {'method': method, 'manager': manager, 'e': e})
                raise
        else:
            LOG.debug('HardwareManager {} does not have method {}'
                      .format(manager, method))

    raise errors.HardwareManagerMethodNotFound(method)


def load_managers():
    """Preload hardware managers into the cache.

    This method is to help warm up the cache for hardware managers when
    called. Used to resolve bug 1490008, where agents can crash the first
    time a hardware manager is needed.

    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    _get_managers()


def cache_node(node):
    """Store the node object in the hardware module.

    Stores the node object in the hardware module to facilitate the
    access of a node information in the hardware extensions.

    If the new node does not match the previously cached one, wait for the
    expected root device to appear.

    :param node: Ironic node object
    """
    global NODE
    new_node = NODE is None or NODE['uuid'] != node['uuid']
    NODE = node

    if new_node:
        LOG.info('Cached node %s, waiting for its root device to appear',
                 node['uuid'])
        # Root device hints, stored in the new node, can change the expected
        # root device. So let us wait for it to appear again.
        dispatch_to_managers('wait_for_disks')


def get_cached_node():
    """Guard function around the module variable NODE."""
    return NODE
