################
OpenStack-Manila
################
Manila driver for Pure Storage FlashBlade

Installation Instructions
-------------------------
This driver has been tested on all release from the Rocky release.

Support for this driver will be on a best-efforts basis and there is no guarantee that driver will work in versions of OpenStack earlier than Rocky.

A prerequisite for installing this driver is that you must have the Manila project already installed in your OpenStack deployment.

In you Manila directory structure you must first create a ``manila/share/drivers/purestorage`` directory and then add the supplied Python driver file into this directory.

You must also modify the ``manila/opts.py`` file to understand that the Pure Storage FlashBlade driver is available for use by performing the following steps:

- Edit the file by adding the following line into the top of the file along with the other ``import`` commands:

.. code-block:: console

    import manila.share.drivers.purestorage.flashblade

- and in the section ``_global_opt_lists`` add the following lines:

.. code-block:: console

    manila.share.drivers.purestorage.flashblade.flashblade_auth_opts,
    manila.share.drivers.purestorage.flashblade.flashblade_extra_opts,
    manila.share.drivers.purestorage.flashblade.flashblade_connection_opts,

- Restart the Manila Share service to enable the Pure Storage FlashBlade driver.

Usage Instructions
==================
==============================
Pure Storage FlashBlade driver
==============================

The Pure Storage FlashBlade driver provides support for managing filesystem shares
on the Pure Storage FlashBlade storage systems.

This section explains how to configure the FlashBlade driver.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create and delete CIFS/NFS shares.

- Extend/Shrink a share.

- Create and delete filesystem snapshots.

- Revert to Snapshot.

- Set access rights to shares.

  Note the following limitations:

  - Only IP and USER access types are supported.

  - Both RW and RO access levels are supported.

External package installation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The driver requires the ``purity_fb`` package for communicating with
FlashBlade systems. Install the package from PyPI using the following command:

.. code-block:: console

   $ pip install purity_fb

Driver configuration
~~~~~~~~~~~~~~~~~~~~

Edit the ``manila.conf`` file, which is usually located under the following
path ``/etc/manila/manila.conf``.

* Add a section for the FlashBlade driver back end.

* Under the ``[DEFAULT]`` section, set the ``enabled_share_backends`` parameter
  with the name of the new back-end section.

Configure the driver back-end section with the parameters below.

* Configure the driver name by setting the following parameter:

  .. code-block:: ini

     share_driver = manila.share.drivers.purestorage.flashblade.FlashBladeShareDriver

* Configure the management and data VIPs of the FlashBlade array by adding the
  following parameters:

  .. code-block:: ini

     flashblade_mgmt_vip = FlashBlade management VIP
     flashblade_data_vip = FlashBlade data VIP

* Configure user credentials:

  The driver requires a FlashBlade user with administrative privileges.
  We recommend creating a dedicated OpenStack user account
  that holds an administrative user role.
  Refer to the FlashBlade manuals for details on user account management.
  Configure the user credentials by adding the following parameters:

  .. code-block:: ini

     flashblade_api = FlashBlade API token for admin-privileged user

* (Optional) Configure File System and Snapshot Eradication:

  The option, when enabled, all FlashBlade file systems and snapshots will
  be eradicated at the time of deletion in Manila. Data will NOT be
  recoverable after a delete with this set to True! When disabled,
  file systems and snapshots will go into pending eradication state
  and can be recovered. The default setting is False.

  .. code-block:: ini

     flashblade_eradicate = { True | False }

* The back-end name is an identifier for the back end.
  We recommend using the same name as the name of the section.
  Configure the back-end name by adding the following parameter:

  .. code-block:: ini

     share_backend_name = back-end name

Configuration example
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: ini

   [DEFAULT]
   enabled_share_backends = flashblade-1

   [flashblade-1]
   share_driver = manila.share.drivers.purestorage.flashblade.FlashBladeShareDriver
   share_backend_name = flashblade-1
   driver_handles_share_servers = false
   flashblade_mgmt_vip = 10.1.2.3
   flashblade_data_vip = 10.1.2.4
   flashblade_api = pureuser API

Driver options
~~~~~~~~~~~~~~

Configuration options specific to this driver:

.. list-table:: Description of Pure Storage FlashBlade share driver configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``flashblade_mgmt_vip`` = ``None``
     - (String) The name (or IP address) for the Pure Storage FlashBlade storage system management port.
   * - ``flashblade_data_vip`` = ``None``
     - (String) The name (or IP address) for the Pure Storage FlashBlade storage system data port.
   * - ``flashblade_api`` = ``None``
     - (String) API token for an administrative level user account.
   * - ``flashblade_eradicate`` = ``True``
     - (Boolean) Enable or disable filesystem and snapshot eradication on delete.

