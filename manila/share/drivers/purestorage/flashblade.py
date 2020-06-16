# Copyright 2018 Pure Storage Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Pure Storage FlashBlade Share Driver
"""

import functools
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import platform

from manila.common import constants
from manila import exception
from manila.i18n import _
from manila.share import driver

HAS_PURITY_FB = True
try:
    import purity_fb
except ImportError:
    HAS_PURITY_FB = False

LOG = logging.getLogger(__name__)

flashblade_connection_opts = [
    cfg.HostAddressOpt('flashblade_mgmt_vip',
                       help='The name (or IP address) for the Pure Storage '
                       'FlashBlade storage system management VIP.'),
    cfg.HostAddressOpt('flashblade_data_vip',
                       help='The name (or IP address) for the Pure Storage '
                       'FlashBlade storage system data VIP.'), ]

flashblade_auth_opts = [
    cfg.StrOpt('flashblade_api',
               help=('API token for an administrative user account'),
               secret=True), ]

flashblade_extra_opts = [
    cfg.BoolOpt('flashblade_eradicate',
                default=False,
                help='When enabled, all FlashBlade file systems and snapshots '
                     'will be eradicated at the time of deletion in Manila. '
                     'Data will NOT be recoverable after a delete with this '
                     'set to True! When disabled, file systems and snapshots '
                     'will go into pending eradication state and can be '
                     'recovered.)'), ]

CONF = cfg.CONF
CONF.register_opts(flashblade_connection_opts)
CONF.register_opts(flashblade_auth_opts)
CONF.register_opts(flashblade_extra_opts)

_MANILA_TO_FLASHBLADE_ACCESS_LEVEL = {
    constants.ACCESS_LEVEL_RW: 'rw',
    constants.ACCESS_LEVEL_RO: 'ro',
}


def purity_fb_to_manila_exceptions(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except purity_fb.rest.ApiException as ex:
            msg = _('Caught exception from purity_fb: %s') % ex
            LOG.exception(msg)
            raise exception.ShareBackendException(msg=msg)
    return wrapper


class FlashBladeShareDriver(driver.ShareDriver):

    VERSION = '10.0'    # driver version
    USER_AGENT_BASE = 'OpenStack Manila'

    def __init__(self, *args, **kwargs):
        super(FlashBladeShareDriver, self).__init__(False, *args, **kwargs)
        self.configuration.append_config_values(flashblade_connection_opts)
        self.configuration.append_config_values(flashblade_auth_opts)
        self.configuration.append_config_values(flashblade_extra_opts)
        self._user_agent = '%(base)s %(class)s/%(version)s (%(platform)s)' % {
            'base': self.USER_AGENT_BASE,
            'class': self.__class__.__name__,
            'version': self.VERSION,
            'platform': platform.platform()
        }

    def do_setup(self, context):
        """Driver initialization"""
        if not HAS_PURITY_FB:
            msg = _("Missing 'purity_fb' python module, ensure the library"
                    " is installed and available.")
            raise exception.ManilaException(message=msg)

        self.api = (
            self._safe_get_from_config_or_fail('flashblade_api'))
        self.management_address = (
            self._safe_get_from_config_or_fail('flashblade_mgmt_vip'))
        self.data_address = (
            self._safe_get_from_config_or_fail('flashblade_data_vip'))

        self._sys = purity_fb.PurityFb(self.management_address)
        self._sys.disable_verify_ssl()
        try:
            self._sys.login(self.api)
            if '1.5' in self._sys.api_version.list_versions().versions:
                self._sys._api_client.user_agent = self._user_agent
        except purity_fb.rest.ApiException as ex:
            msg = _("Exception when logging into the array: %s\n") % ex
            LOG.exception(msg)
            raise exception.ManilaException(message=msg)

        backend_name = self.configuration.safe_get('share_backend_name')
        self._backend_name = backend_name or self.__class__.__name__

        LOG.debug('setup complete')

    def _update_share_stats(self, data=None):
        """Retrieve stats info from share group."""
        (free_capacity_bytes, physical_capacity_bytes,
         provisioned_cap_bytes,
         data_reduction) = self._get_available_capacity()

        data = dict(
            share_backend_name=self._backend_name,
            vendor_name='PURE STORAGE',
            driver_version=self.VERSION,
            storage_protocol='NFS_CIFS',
            data_reduction=data_reduction,
            total_capacity_gb=float(physical_capacity_bytes) / units.Gi,
            free_capacity_gb=float(free_capacity_bytes) / units.Gi,
            provisioned_capacity_gb=float(provisioned_cap_bytes) / units.Gi,
            snapshot_support=True,
            create_share_from_snapshot_support=False,
            mount_snapshot_support=False,
            revert_to_snapshot_support=False)

        super(FlashBladeShareDriver, self)._update_share_stats(data)

    def _get_available_capacity(self):
        space = self._sys.arrays.list_arrays_space()
        array_space = space.items[0]
        data_reduction = array_space.space.data_reduction
        physical_capacity_bytes = array_space.capacity
        used_capacity_bytes = array_space.space.total_physical
        free_capacity_bytes = physical_capacity_bytes - used_capacity_bytes
        provisioned_capacity_bytes = array_space.space.unique
        return (free_capacity_bytes, physical_capacity_bytes,
                provisioned_capacity_bytes, data_reduction)

    def _safe_get_from_config_or_fail(self, config_parameter):
        config_value = self.configuration.safe_get(config_parameter)
        if not config_value:
            reason = (_("%(config_parameter)s configuration parameter "
                        "must be specified") %
                      {'config_parameter': config_parameter})
            LOG.error(reason)
            raise exception.BadConfigurationException(reason=reason)
        return config_value

    def _make_source_name(self, snapshot):
        return 'share-%s-manila' % snapshot['share_instance_id']

    def _make_share_name(self, manila_share):
        return 'share-%s-manila' % manila_share['id']

    def _get_flashblade_access_level(self, access):
        """Translates between Manila access levels to FlashBlade ones"""
        access_level = access['access_level']
        try:
            return _MANILA_TO_FLASHBLADE_ACCESS_LEVEL[access_level]
        except KeyError:
            raise exception.InvalidShareAccessLevel(level=access_level)

    @purity_fb_to_manila_exceptions
    def _get_full_nfs_export_path(self, export_path):
        # Until we can interrogate purenetwork and puresubnet use config data
        subnet_ip = self.data_address
        return '{subnet_ip}:/{export_path}'.format(
            subnet_ip=subnet_ip,
            export_path=export_path)

    @purity_fb_to_manila_exceptions
    def _get_full_cifs_export_path(self, export_path):
        # Until we can interrogate purenetwork and puresubnet use config data
        subnet_ip = self.data_address
        return '\\{subnet_ip}\{export_path}'.format(
            subnet_ip=subnet_ip,
            export_path=export_path)

    @purity_fb_to_manila_exceptions
    def _get_flashblade_filesystem_by_name(self, name):
        try:
            filesys = []
            filesys.append(name)
            res = self._sys.file_systems.list_file_systems(names=filesys)
            if not res.items[0]:
                msg = (_('Filesystem not found on FlashBlade by name: %s') %
                       name)
                LOG.error(msg)
                raise exception.ShareResourceNotFound(share_id=name)
            else:
                return res.items[0]
        except exception.InvalidShare:
            msg = (_('Filesystem not found on FlashBlade by name: %s') %
                   name)
            LOG.error(msg)
            raise exception.ShareResourceNotFound(share_id=name)
        return None

    def _get_flashblade_filesystem(self, manila_share):
        filesystem_name = self._make_share_name(manila_share)
        return self._get_flashblade_filesystem_by_name(filesystem_name)

    def _get_flashblade_snapshot_by_name(self, name):
        try:
            resu = self._sys.file_system_snapshots.list_file_system_snapshots(
                filter=name)
        except exception.InvalidShare:
            msg = (_('Snapshot not found on the FlashBlade by its name: %s') %
                   name)
            LOG.error(msg)
            raise exception.ShareSnapshotNotFound(snapshot_id=name)
        return resu.items[0]

    @purity_fb_to_manila_exceptions
    def _create_filesystem_export(self, flashblade_filesystem):
        flashblade_export = flashblade_filesystem.add_export(permissions=[])
        return {
            'path': self._get_full_nfs_export_path(
                flashblade_export.get_export_path()),
            'is_admin_only': False,
            'metadata': {},
        }

    @purity_fb_to_manila_exceptions
    def _resize_share(self, share, new_size):
        dataset_name = self._make_share_name(share)
        try:
            self._get_flashblade_filesystem_by_name(dataset_name)
        except exception.ShareResourceNotFound:
            message = ("share %(dataset_name)s not found on FlashBlade, skip "
                       "extend")
            LOG.warning(message, {"dataset_name": dataset_name})
            return
        attr = {}
        attr['provisioned'] = new_size * units.Gi
        n_attr = purity_fb.FileSystem(**attr)
        self._sys.file_systems.update_file_systems(
            name=dataset_name, attributes=n_attr)

    @purity_fb_to_manila_exceptions
    def _update_nfs_access(self, share, access_rules):
        dataset_name = self._make_share_name(share)
        try:
            self._get_flashblade_filesystem_by_name(dataset_name)
        except exception.ShareResourceNotFound:
            message = ("share %(dataset_name)s not found on FlashBlade, skip "
                       "update nfs access")
            LOG.warning(message, {"dataset_name": dataset_name})
            return
        nfs_rules = ""
        for access in access_rules:
            if access['access_type'] == 'ip':
                line = (access['access_to'] +
                        '(' + self._get_flashblade_access_level(access) +
                        ',no_root_squash) ')
                nfs_rules += line
        message = ("rules are %(nfs_rules)s, info "
                   "update nfs access")
        LOG.error(message, {"nfs_rules": nfs_rules})

        self._sys.file_systems.update_file_systems(
            name=dataset_name,
            attributes=purity_fb.FileSystem(
                nfs=purity_fb.NfsRule(rules=nfs_rules)))

    @purity_fb_to_manila_exceptions
    def create_share(self, context, share, share_server=None):

        size = share['size'] * units.Gi
        share_name = self._make_share_name(share)

        if share['share_proto'] == 'NFS':
            if '1.6' in self._sys.api_version.list_versions().versions:
                flashblade_fs = purity_fb.FileSystem(
                    name=share_name,
                    provisioned=size,
                    hard_limit_enabled=True,
                    fast_remove_directory_enabled=True,
                    snapshot_directory_enabled=True,
                    nfs=purity_fb.NfsRule(v3_enabled=True, rules='', v4_1_enabled=True))
            else:
                flashblade_fs = purity_fb.FileSystem(
                    name=share_name,
                    provisioned=size,
                    hard_limit_enabled=True,
                    fast_remove_directory_enabled=True,
                    snapshot_directory_enabled=True,
                    nfs=purity_fb.NfsRule(enabled=True,
                                          rules=''))
            self._sys.file_systems.create_file_systems(flashblade_fs)
            location = self._get_full_nfs_export_path(share_name)
        elif share['share_proto'] == 'CIFS':
            flashblade_fs = purity_fb.FileSystem(
                name=share_name,
                provisioned=size,
                hard_limit_enabled=True,
                fast_remove_directory_enabled=True,
                snapshot_directory_enabled=True,
                smb=purity_fb.ProtocolRule(enabled=True))
            self._sys.file_systems.create_file_systems(flashblade_fs)
            location = self._get_full_cifs_export_path(share_name)
        else:
            message = (_('Unsupported share protocol: %(proto)s.') %
                       {'proto': share['share_proto']})
            LOG.error(message)
            raise exception.InvalidShare(reason=message)

        return location

    @purity_fb_to_manila_exceptions
    def create_snapshot(self, context, snapshot, share_server=None):
        """Called to create a snapshot"""
        source = []
        flashblade_filesystem = self._make_source_name(snapshot)
        source.append(flashblade_filesystem)
        try:
            self._sys.file_system_snapshots.create_file_system_snapshots(
                sources=source,
                suffix=purity_fb.SnapshotSuffix(snapshot['id']))
        except exception.ShareResourceNotFound:
            message = ("share %(dataset_name)s not found on FlashBlade, skip "
                       "create")
            LOG.error(message, {"dataset_name": flashblade_filesystem})
            raise exception.InvalidShare(reason=message)

    @purity_fb_to_manila_exceptions
    def delete_share(self, context, share, share_server=None):
        """Called to delete a share"""
        dataset_name = self._make_share_name(share)
        try:
            self._get_flashblade_filesystem_by_name(dataset_name)
        except exception.ShareResourceNotFound:
            message = ("share %(dataset_name)s not found on FlashBlade, skip "
                       "delete")
            LOG.warning(message, {"dataset_name": dataset_name})
            return
        self._sys.file_systems.update_file_systems(
            name=dataset_name,
            attributes=purity_fb.FileSystem(
                nfs=purity_fb.NfsRule(v3_enabled=False,
                                      v4_1_enabled=False),
                smb=purity_fb.ProtocolRule(enabled=False),
                destroyed=True))
        if self.configuration.flashblade_eradicate:
            self._sys.file_systems.delete_file_systems(dataset_name)

    @purity_fb_to_manila_exceptions
    def delete_snapshot(self, context, snapshot, share_server=None):
        """Caled to delete a snapshot"""
        dataset_name = self._make_source_name(snapshot)
#        filt = ('source=\'' +
#                dataset_name +
#                '\' and suffix=\'' +
#                snapshot['id'] +
#                '\'')
        filt = 'source=\'{0}\' and suffix=\'{1}\''.format(dataset_name, snapshot['id'])
#        name = (dataset_name +
#                "." +
#                snapshot['id'])
        name = '{0},{1}'.format(dataset_name, snapshot['id'])
        try:
            flashblade_snapshot = (
                self._get_flashblade_snapshot_by_name(filt))
        except exception.ShareResourceNotFound:
            message = ("snapshot %(snapshot)s not found on FlashBlade, skip "
                       "delete")
            LOG.warning(message, {"snapshot": flashblade_snapshot})
            return
        self._sys.file_system_snapshots.update_file_system_snapshots(
            name=name,
            attributes=purity_fb.FileSystemSnapshot(destroyed=True))
        if self.configuration.flashblade_eradicate:
            self._sys.file_system_snapshots.delete_file_system_snapshots(
                name=name)

    def ensure_share(self, context, share, share_server=None):
        """Dummy - called to ensure share is exported.
        All shares created on a FlashBlade are guaranteed to
        be exported so this check is redundant"""

    def update_access(self, context, share, access_rules, add_rules,
                      delete_rules, share_server=None):
        # We will use the access_rules list to bulk update access
        if share['share_proto'] == 'NFS':
            self._update_nfs_access(share, access_rules)
        # TODO(SD): add CIFS access stuff when available

    def get_network_allocations_number(self):
        return 0

    def extend_share(self, share, new_size, share_server=None):
        """uses resize_share to extend a share"""
        self._resize_share(share, new_size)

    def shrink_share(self, share, new_size, share_server=None):
        """uses resize_share to shrink a share"""
        self._resize_share(share, new_size)
