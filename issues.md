Notes for InfraRed
==================

* The PyPI packages are not maintained and should be removed: https://pypi.org/project/infrared/
* The "stable" branch is unversioned and un-tagged
* We are installing latest versions of Python libraries, a terrible practice
* Do *not* use the prefix argument in virsh. It seems to confuse the overcloud installer.

Patches:

* https://github.com/redhat-openstack/infrared/issues/337
* https://github.com/redhat-openstack/infrared/commit/0508e1623cdc997356584f64850efae584caea7d
* Nova is doing wrong health check (tripleo)
  https://github.com/openstack/tripleo-common/commit/79bb8e736d29457f932951e805e218a32980e970
  See also:
  https://github.com/openstack/tripleo-common/commit/7f9606ff47f03162e5d7305aaca2af5d1faecd87
* ceph-mgr deploy is broken (tripleo)
  https://bugzilla.redhat.com/show_bug.cgi?id=1640523
  https://github.com/redhat-openstack/infrared/commit/15b09251c10f5dd218657573add474ffd7c4f2d7
