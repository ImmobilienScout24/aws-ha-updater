from unittest import TestCase

from mock import Mock, patch
from boto.ec2.elb import ELBConnection
from boto.ec2 import EC2Connection
from boto.ec2.autoscale import AutoScalingGroup, AutoScaleConnection

from aws_updater.asg import ASGUpdater


class ASGUpdaterTests(TestCase):

    def setUp(self):
        self.asg = Mock(AutoScalingGroup, max_size=0, min_size=0, desired_capacity=0, launch_config_name="any-lc")
        self.asg.instances = []
        self.asg.name = "any-asg-name"
        self.asg_conn = Mock(AutoScaleConnection)
        self.ec2_conn = Mock(EC2Connection)
        self.elb_conn = Mock(ELBConnection)
        patch("aws_updater.asg.print", create=True).start()
        self.asg_updater = ASGUpdater(self.asg,
                                      self.asg_conn,
                                      self.ec2_conn,
                                      self.elb_conn)

    def tearDown(self):
        patch.stopall()

    def test_should_terminate_instances(self):
        self.asg_updater._terminate_instances(["any-machine-id", "any-other-machine-id"])

        self.ec2_conn.terminate_instances.assert_called_with(["any-machine-id", "any-other-machine-id"])

    def test_should_terminate_old_instances_when_committing_update(self):
        self.asg.instances = [Mock(instance_id="1", launch_config_name="any-lc"),
                              Mock(instance_id="resource_id_of_instance_with_old_lc", launch_config_name="any-old-lc"),
                              Mock(instance_id="3", launch_config_name="any-lc")]

        with patch("aws_updater.asg.ASGUpdater._terminate_instances") as terminate_instances:
            self.asg_updater.commit_update()
            terminate_instances.assert_called_with(["resource_id_of_instance_with_old_lc"])

    def test_should_terminate_new_instances_when_rolling_back_update(self):
        self.asg.instances = [Mock(instance_id="resource_id_of_instance_with_new_lc-1", launch_config_name="any-lc"),
                              Mock(instance_id="2", launch_config_name="any-old-lc"),
                              Mock(instance_id="resource_id_of_instance_with_new_lc-2", launch_config_name="any-lc")]

        with patch("aws_updater.asg.ASGUpdater._terminate_instances") as terminate_instances:
            self.asg_updater.rollback()
            terminate_instances.assert_called_with(['resource_id_of_instance_with_new_lc-1', 'resource_id_of_instance_with_new_lc-2'])

    def test_should_resume_processes_when_committing_update(self):
        self.asg_updater.commit_update()

        self.asg.resume_processes.assert_called_with()

    def test_should_not_resume_processes_when_rolling_back_update(self):
        self.asg_updater.rollback()

        self.assertFalse(self.asg.resume_processes.called)

    def test_should_count_instances_that_might_serve_requests(self):
        self.asg.instances = [Mock(lifecycle_state="Pending"),
                              Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="Rebooting"),
                              Mock(lifecycle_state="AFKing"),
                              Mock(lifecycle_state="Terminating"),
                              Mock(lifecycle_state="OutOfService")]

        actual_count = self.asg_updater.count_running_instances()

        self.assertEqual(actual_count, 3)

    def test_should_stop_all_processes_except_specified_ones_when_scaling_out(self):
        self.asg_updater.scale_out()

        self.asg.suspend_processes.assert_called_with()
        self.asg.resume_processes.assert_called_with(['Launch', 'Terminate', 'HealthCheck', 'AddToLoadBalancer'])

    def test_should_update_asg_parameters_to_double_running_instances_when_scaling_out(self):
        self.asg.min_size = 3
        self.asg.max_size = 6
        self.asg.desired_capacity = 3
        self.asg.instances = [Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="InService"),
                              Mock(lifecycle_state="InService")]

        self.asg_updater.scale_out()

        self.assertEqual(self.asg.min_size, 6)
        self.assertEqual(self.asg.max_size, 9)
        self.assertEqual(self.asg.desired_capacity, 6)
        self.asg.update.assert_called_with()
