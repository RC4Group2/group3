#!/usr/bin/env python
import roslib; roslib.load_manifest('ar_follower')
import actionlib
import rospy
import smach
import smach_ros
import tf

import math

# TODO: replace this with the real message type, as soon as I have real data to test with ...

from actionlib_msgs.msg import GoalStatus
#from brics_msgs.msg import marker_detection
from mbn_msgs.msg import MarkersPoses
from geometry_msgs.msg import Quaternion, PoseStamped, Point
from move_base_msgs.msg import *
from smach_ros import SimpleActionState

class Init(smach.State):
    def __init__(self):
        smach.State.__init__(self, 
                             outcomes=['done', 'keep_looking', 'not_seen', 'tag_seen'],
                             input_keys=['tag_ids', 'init_iter_count'],
                             output_keys=['tag_location', 'init_iter_count'])
        #self.tag_subscriber = rospy.Subscriber("/markers_poses_topic", marker_detection, self.marker_cb)
        self.tag_subscriber = rospy.Subscriber("/markers_poses_topic", MarkersPoses, self.marker_cb)
        self.curr_msg = None

    def marker_cb(self, marker_msg):
        self.curr_msg = marker_msg
        
    def execute(self, userdata):
        print "executing state ar_follower.Init with id list: %r" % (userdata.tag_ids)
        if userdata.tag_ids == []:
            return 'done'
        # make sure we get the *next* tag detection message
        self.curr_msg = None
        while self.curr_msg is None:
            rospy.sleep(1.0)
        # TODO: this is sloppy ... should cycle through all and choose best, rather than just looking for first
        # however, it shouldn't matter, as the next callback will find the following marker
        for marker_pose in self.curr_msg.markersPoses:
            if marker_pose.marker_id in userdata.tag_ids:
                marker_x = marker_pose.poseWRTRobotFrame.position.x
                marker_y = marker_pose.poseWRTRobotFrame.position.y
                quat = marker_pose.poseWRTRobotFrame.orientation
                euler = tf.transformations.euler_from_quaternion([quat.x, quat.y, quat.z, quat.w])
                marker_th = euler[2]
                # TODO: is this thread-safe? I'm still confused w/ python's threading...
                userdata.tag_location=[marker_x, marker_y, marker_th]
                userdata.init_iter_count = 0 # gotta reset this
                return 'tag_seen'

        userdata.init_iter_count += 1
        if userdata.init_iter_count < 10:
            return 'keep_looking'
        else:
            userdata.init_iter_count = 0
            return 'not_seen'

class GotoTag(smach.State):
    def __init__(self):
        smach.State.__init__(self, outcomes=['at_tag', 'goto_failed', 'new_tag'],
                             input_keys=['tag_location', 'tag_ids'],
                             output_keys=['tag_location', 'tag_ids'])
        self.controller_client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        print "waiting for move_base..."
        self.controller_client.wait_for_server()
        print "got move_base"
        #self.tag_subscriber = rospy.Subscriber("/markers_poses_topic", marker_detection, self.marker_cb)
        self.tag_subscriber = rospy.Subscriber("/markers_poses_topic", MarkersPoses, self.marker_cb)
        self.curr_msg = None

    def marker_cb(self, marker_msg):
        self.curr_msg = marker_msg

    def execute(self, userdata):
        goal_msg = MoveBaseGoal()
        goal_pose = PoseStamped()
        # TODO: this should get the frame from the input marker message...
        goal_pose.header.frame_id = "/base_link"
        goal_pose.header.stamp = rospy.Time.now()
        goal_pt = Point(userdata.tag_location[0], userdata.tag_location[1], 0.0)
        goal_pose.pose.position = goal_pt
        # TODO: this should be aligned with the april tag pose!
        qq = tf.transformations.quaternion_from_euler(0, 0, userdata.tag_location[2])
        goal_pose.pose.orientation = Quaternion(*qq)
        goal_msg.target_pose = goal_pose
        self.controller_client.send_goal(goal_msg)
        goal_status = self.controller_client.get_state()
        while goal_status in [GoalStatus.PENDING, GoalStatus.ACTIVE]:
            for marker_pose in self.curr_msg.markersPoses:
                if marker_pose.marker_id in userdata.tag_ids[1:]:
                    marker_x = marker_pose.poseWRTRobotFrame.position.x
                    marker_y = marker_pose.poseWRTRobotFrame.position.y
                    quat = marker_pose.poseWRTRobotFrame.orientation
                    euler = tf.transformations.euler_from_quaternion([quat.x, quat.y, quat.z, quat.w])
                    marker_th = euler[2]
                    # TODO: is this thread-safe? I'm still confused w/ python's threading...
                    userdata.tag_location=[marker_x, marker_y, marker_th]
                    tag_idx = userdata.tag_ids.index(marker_pose.marker_id)
                    userdata.tag_ids = userdata.tag_ids[tag_idx:]
                    return 'new_tag'
            rospy.sleep(0.2)
            goal_status = self.controller_client.get_state()

        self.controller_client.wait_for_result()
        print "got controller result!"

        controller_state = self.controller_client.get_state()
        if controller_state == GoalStatus.PREEMPTED:
            return 'goto_failed'
        elif controller_state == GoalStatus.ABORTED:
            print "ar_follower.GotoTag's controller call aborted!"
            return 'goto_failed'
        elif controller_state == GoalStatus.SUCCEEDED:
            print "ar_follower.GotoTag's controller call succeeded!"
            userdata.tag_ids = userdata.tag_ids[1:]
            return 'at_tag'
        else:
            print "ar_follower.GotoTag's controller returned %r" % (controller_state)
            return 'goto_failed'

#def monitor_cb(userdata, msg):
#    # needs to return False when we have data that we need ...
#    # TODO: needs to actually check *every* ID in the list, not just the first one..or maybe not, if we need to follow the list in order....
#    print "called monitor_cb with userdata ids: %r \n \n and msg: %r"% (userdata, msg)
#    if msg.marker_id in userdata.tag_ids[1:]:
#        print "in ar_follow3er.monitor_cb. about to update userdata.marker_ids!"
#        tag_idx = userdata.tag_ids.index(msg.marker_id)
#        userdata.tag_ids = userdata.tag_ids[tag_idx:]
#        userdata.tag_location = [msg.marker_x, msg.marker_y]
#        return False
#    else:
#        return True

## whenever either child terminates, want to preempt the other...
#def child_term_cb(outcome_map):
#    return False

#def out_cb(outcome_map):
#    if outcome_map['GOTO_TAG'] == 'succeeded':
#        return 'at_tag'
#    elif outcome_map['GOTO_TAG'] == 'aborted':
#        return 'goto_failed'
#    # in this case, we received a new message with higher probability ... already dealt with userdata
#    if outcome_map['MONITOR_TAGS'] == 'invalid':
#        return 'new_tag'
#    return 'goto_failed'
        


def main():
    rospy.init_node('ar_follower')
    sm = smach.StateMachine(outcomes=['done'])
    #sm.userdata.tag_ids = [19, 22, 24, 26, 38]
    #sm.userdata.tag_ids = [0, 1, 2, 3, 4, 5, 6, 7, 8, 34]
    sm.userdata.tag_ids = [10, 11, 12, 13, 14, 15, 16, 17, 35]
    sm.userdata.init_iter_count = 0

    #path_concurrence = smach.Concurrence(outcomes=['at_tag', 'goto_failed', 'new_tag'],
    #                                     input_keys = ['tag_location', 'tag_ids'],
    #                                     output_keys = ['tag_location', 'tag_ids'],
    #                                     default_outcome='at_tag',
    #                                     child_termination_cb=child_term_cb,
    #                                     outcome_cb=out_cb)
    #with path_concurrence:
    #    smach.Concurrence.add('GOTO_TAG', GotoTag())
    #    smach.Concurrence.add('MONITOR_TAGS', 
    #                          smach_ros.MonitorState("/markers_poses_topic", marker_detection, monitor_cb,
    #                                                 input_keys = ['tag_ids'],
    #                                                 output_keys = ['tag_ids', 'tag_location']))
    
    with sm:
        smach.StateMachine.add('INIT', Init(), 
                               transitions={'done':'done', 
                                            'not_seen':'TURN', 
                                            'keep_looking':'INIT', 
                                            'tag_seen':'FOLLOW_PATH'})
        goal_msg = MoveBaseGoal()
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = "/base_link"
        goal_pose.header.stamp = rospy.Time.now()
        goal_pt = Point(0.0, 0.0, 0.0)
        goal_pose.pose.position = goal_pt
        qq = tf.transformations.quaternion_from_euler(0, 0, math.pi/6)
        goal_pose.pose.orientation = Quaternion(*qq)
        goal_msg.target_pose = goal_pose
        smach.StateMachine.add('TURN',
                               SimpleActionState('move_base', MoveBaseAction, 
                                                 goal=goal_msg),
                               transitions={'succeeded':'INIT', 
                                            'preempted':'INIT',
                                            'aborted':'INIT'})
        
        smach.StateMachine.add('FOLLOW_PATH', GotoTag(),
                               transitions={'at_tag':'INIT', 
                                            'goto_failed':'INIT',
                                            'new_tag':'FOLLOW_PATH'})
   
    sis = smach_ros.IntrospectionServer('smach_server', sm, '/SM_ROOT')
    sis.start()
    sm.execute()
    rospy.spin()
    sis.stop()
    


if __name__=="__main__":
    main()
