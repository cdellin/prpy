#!/usr/bin/env python

# Copyright (c) 2015, Carnegie Mellon University
# All rights reserved.
# Authors: Siddhartha Srinivasa <siddh@cs.cmu.edu>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# - Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of Carnegie Mellon University nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import logging
import numpy
import openravepy
import itertools
import time
from base import BasePlanner, PlanningError, PlanningMethod
import prpy.util
from enum import Enum

logger = logging.getLogger('planning')


class Status(Enum):
    '''
    TERMINATE - stop, exit gracefully, and return current trajectory
    CACHE_AND_CONTINUE - save the current trajectory and CONTINUE.
                         return the saved trajectory if Exception.
    CONTINUE - keep going
    '''
    TERMINATE = -1
    CACHE_AND_CONTINUE = 0
    CONTINUE = 1


class VectorFieldPlanner(BasePlanner):
    def __init__(self):
        super(VectorFieldPlanner, self).__init__()

    def __str__(self):
        return 'VectorFieldPlanner'

    @PlanningMethod
    def PlanToEndEffectorPose(self, robot, goal_pose, timelimit=5.0,
                              pose_error_tol=0.01, **kw_args):
        """
        Plan to an end effector pose by following a geodesic loss function
        in SE(3) via an optimized Jacobian.

        @param robot
        @param goal_pose desired end-effector pose
        @param timelimit time limit before giving up
        @param pose_error_tol in meters
        @return traj
        """
        manip = robot.GetActiveManipulator()

        def vf_geodesic():
            twist = prpy.util.GeodesicTwist(manip.GetEndEffectorTransform(),
                                            goal_pose)
            dqout, tout = prpy.util.ComputeJointVelocityFromTwist(
                                robot, twist)
            # Go as fast as possible
            dqout = min(abs(robot.GetDOFVelocityLimits()/dqout))*dqout

            return dqout

        def CloseEnough():
            pose_error = prpy.util.GeodesicDistance(
                        manip.GetEndEffectorTransform(),
                        goal_pose)
            if pose_error < pose_error_tol:
                return Status.TERMINATE
            return Status.CONTINUE

        return self.FollowVectorField(robot, vf_geodesic,
                                      CloseEnough, timelimit)

    @PlanningMethod
    def PlanToEndEffectorOffset(self, robot, direction, distance,
                                max_distance=None, timelimit=5.0,
                                position_tolerance=0.01,
                                angular_tolerance=0.15,
                                **kw_args):
        """
        Plan to a desired end-effector offset with move-hand-straight
        constraint. movement less than distance will return failure. The motion
        will not move further than max_distance.
        @param robot
        @param direction unit vector in the direction of motion
        @param distance minimum distance in meters
        @param max_distance maximum distance in meters
        @param timelimit timeout in seconds
        @param position_tolerance constraint tolerance in meters
        @param angular_tolerance constraint tolerance in radians
        @return traj
        """
        if distance < 0:
            raise ValueError('Distance must be non-negative.')
        elif numpy.linalg.norm(direction) == 0:
            raise ValueError('Direction must be non-zero')
        elif max_distance is not None and max_distance < distance:
            raise ValueError('Max distance is less than minimum distance.')
        elif position_tolerance < 0:
            raise ValueError('Position tolerance must be non-negative.')
        elif angular_tolerance < 0:
            raise ValueError('Angular tolerance must be non-negative.')

        # Normalize the direction vector.
        direction = numpy.array(direction, dtype='float')
        direction /= numpy.linalg.norm(direction)

        # Default to moving an exact distance.
        if max_distance is None:
            max_distance = distance

        manip = robot.GetActiveManipulator()
        Tstart = manip.GetEndEffectorTransform()

        def vf_straightline():
            twist = prpy.util.GeodesicTwist(manip.GetEndEffectorTransform(),
                                            Tstart)
            twist[0:3] = direction
            dqout, tout = prpy.util.ComputeJointVelocityFromTwist(
                    robot, twist)

            # Go as fast as possible
            dqout = min(abs(robot.GetDOFVelocityLimits()/dqout))*dqout
            return dqout

        def TerminateMove():
            '''
            Fail if deviation larger than position and angular tolerance.
            Succeed if distance moved is larger than max_distance.
            Cache and continue if distance moved is larger than distance.
            '''
            Tnow = manip.GetEndEffectorTransform()
            error = prpy.util.GeodesicError(Tstart, Tnow)
            if numpy.fabs(error[3]) > angular_tolerance:
                raise PlanningError('Deviated from orientation constraint.')
            distance_moved = numpy.dot(error[0:3], direction)
            position_deviation = numpy.linalg.norm(error[0:3] -
                                                   distance_moved*direction)
            if position_deviation > position_tolerance:
                raise PlanningError('Deviated from straight line constraint.')

            if distance_moved > max_distance:
                return Status.TERMINATE

            if distance_moved > distance:
                return Status.CACHE_AND_CONTINUE

            return Status.CONTINUE

        return self.FollowVectorField(robot, vf_straightline,
                                      TerminateMove, timelimit)

    @PlanningMethod
    def PlanToTSR(self, robot, tsrchains,
                  timelimit=1.0, ranker=None, max_deviation=2*numpy.pi,
                  **kw_args):
        """
        Plan to a desired TSR set using a-priori goal sampling.  This samples
        goals from the specified TSRs, while using the vector field planner to
        attempt to plan to the resulting affine transformations.

        This will currently return failure if the provided TSR chains require
        any constraint other than goal sampling.

        @param robot the robot whose active manipulator will be used
        @param tsrchains a list of TSR chains that define a goal set
        @param timelimit the maximum time to spend sampling goal TSR chains
        @param max_deviation the maximum per-joint deviation from current pose
                             that can be considered a valid sample.
        @return traj a trajectory that satisfies the specified TSR chains
        """
        # Plan using the active manipulator.
        with robot.GetEnv():
            manipulator = robot.GetActiveManipulator()

            # Distance from current configuration is default ranking.
            if ranker is None:
                from ..ik_ranking import NominalConfiguration
                ranker = NominalConfiguration(manipulator.GetArmDOFValues(),
                                              max_deviation=max_deviation)

        # Test for tsrchains that cannot be handled.
        for tsrchain in tsrchains:
            if tsrchain.sample_start or tsrchain.constrain:
                raise PlanningError(
                    'Cannot handle start or trajectory-wide TSR constraints.')
        tsrchains = [t for t in tsrchains if t.sample_goal]

        # Create an iterator that cycles through each TSR chain.
        tsr_cycler = itertools.cycle(tsrchains)

        # Create an iterator that cycles TSR chains until the timelimit.
        timelimit_time = time.time() + timelimit
        tsr_sampler = itertools.takewhile(
            lambda v: time.time() < timelimit_time, tsr_cycler)

        # Sample a list of TSR poses and collate valid IK solutions.
        for tsrchain in tsr_sampler:
            ik_goal = tsrchain.sample()
            try:
                return self.PlanToEndEffectorPose(
                    robot, ik_goal,
                    timelimit=min(0.1, timelimit_time - time.time()),
                    **kw_args
                )
            except PlanningError:
                continue

        # If none of the planning attempts succeeded, report failure.
        raise PlanningError('Reached timeout without finding solution')

    @PlanningMethod
    def FollowVectorField(self, robot, fn_vectorfield, fn_terminate,
                          timelimit=5.0, dq_tol=0.0001, **kw_args):
        """
        Follow a joint space vectorfield to termination.

        @param robot
        @param fn_vectorfield a vectorfield of joint velocities
        @param fn_terminate custom termination condition
        @param timelimit time limit before giving up
        @param dq_tol velocity tolerance for termination
        @param kw_args keyword arguments to be passed to fn_vectorfield
        @return traj
        """
        start_time = time.time()

        try:
            with robot:
                manip = robot.GetActiveManipulator()
                robot.SetActiveDOFs(manip.GetArmIndices())
                # Populate joint positions and joint velocities
                cspec = manip.GetArmConfigurationSpecification('quadratic')
                cspec.AddDerivativeGroups(1, False)
                cspec.AddDeltaTimeGroup()
                cspec.ResetGroupOffsets()
                qtraj = openravepy.RaveCreateTrajectory(self.env,
                                                        'GenericTrajectory')
                qtraj.Init(cspec)
                cached_traj = None

                dqout = robot.GetActiveDOFVelocities()
                dt = min(robot.GetDOFResolutions() /
                         robot.GetDOFVelocityLimits())
                while True:
                    # Check for a timeout.
                    current_time = time.time()
                    if (timelimit is not None and
                            current_time - start_time > timelimit):
                        raise PlanningError('Reached time limit.')

                    # Check for collisions.
                    if self.env.CheckCollision(robot):
                        raise PlanningError('Encountered collision.')
                    if robot.CheckSelfCollision():
                        raise PlanningError('Encountered self-collision.')

                    # Add to trajectory
                    waypoint = []
                    q_curr = robot.GetActiveDOFValues()
                    waypoint.append(q_curr)  # joint position
                    waypoint.append(dqout)   # joint velocity
                    waypoint.append([dt])    # delta time
                    waypoint = numpy.concatenate(waypoint)
                    qtraj.Insert(qtraj.GetNumWaypoints(), waypoint)
                    dqout = fn_vectorfield()
                    if (numpy.linalg.norm(dqout) < dq_tol):
                        raise PlanningError('Local minimum, \
                                             unable to progress')

                    status = fn_terminate()

                    if status == Status.CACHE_AND_CONTINUE:
                        cached_traj = prpy.util.CopyTrajectory(qtraj)

                    if status == Status.TERMINATE:
                        break

                    qnew = q_curr + dqout*dt
                    robot.SetActiveDOFValues(qnew)

        except PlanningError as e:
            if cached_traj is not None:
                logger.warning('Terminated early: %s', e.message)
                return cached_traj
            else:
                raise

        return qtraj
