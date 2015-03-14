#!/usr/bin/env python

# Copyright (c) 2013, Carnegie Mellon University
# All rights reserved.
# Authors: Michael Koval <mkoval@cs.cmu.edu>
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

import logging, numpy, openravepy, os, tempfile
from ..util import CopyTrajectory, SimplifyTrajectory, HasAffineDOFs
from base import BasePlanner, PlanningError, PlanningMethod, UnsupportedPlanningError
from openravepy import PlannerStatus 


class OpenRAVERetimer(BasePlanner):
    def __init__(self, algorithm):
        super(OpenRAVERetimer, self).__init__()
        self.algorithm = algorithm

    @PlanningMethod
    def RetimeTrajectory(self, robot, path, **kw_args):
        RetimeTrajectory = openravepy.planningutils.RetimeTrajectory

        cspec = path.GetConfigurationSpecification()
        if HasAffineDOFs(cspec):
            raise UnsupportedPlanningError('OpenRAVERetimer does not support paths with affine DOFs')

        """
        group = cspec.GetGroupFromName('joint_values')
        if group.interpolation != 'linear':
            raise PlanningError(
                'Path has interpolation of type "{:s}"; only "linear"'
                ' interpolation is supported.'.format(
                    group.interpolation
                )
            )
        """

        # Copy the input trajectory into the planning environment. This is
        # necessary for two reasons: (1) the input trajectory may be in another
        # environment and/or (2) the retimer modifies the trajectory in-place.
        input_path = CopyTrajectory(path, env=self.env)

        # Remove co-linear waypoints. Some of the default OpenRAVE retimers do
        # not perform this check internally (e.g. ParabolicTrajectoryRetimer).
        output_traj = SimplifyTrajectory(input_path, robot)

        # Compute the timing. This happens in-place.
        status = RetimeTrajectory(output_traj, False, 1., 1., self.algorithm)

        if status not in [ PlannerStatus.HasSolution,
                           PlannerStatus.InterruptedWithSolution ]:
            raise PlanningError('Retimer returned with status {0:s}.'.format(
                                str(status)))

        return output_traj


class ParabolicRetimer(OpenRAVERetimer):
    def __init__(self):
        super(ParabolicRetimer, self).__init__('ParabolicTrajectoryRetimer')


class ParabolicSmoother(OpenRAVERetimer):
    def __init__(self):
        super(ParabolicSmoother, self).__init__('HauserParabolicSmoother')

class OpenRAVEAffineRetimer(BasePlanner):

    def __init__(self,):
        super(OpenRAVEAffineRetimer, self).__init__()

    @PlanningMethod
    def RetimeTrajectory(self, robot, path, **kw_args):

        RetimeTrajectory = openravepy.planningutils.RetimeAffineTrajectory

        cspec = path.GetConfigurationSpecification()

        # Check for anything other than affine dofs in the traj
        # TODO: Better way to do this?
        affine_groups = ['affine_transform',
                         'affine_velocities',
                         'affine_accelerations']

        for group in cspec.GetGroups():
            found = False
            for group_name in affine_groups:
                if group_name in group.name: # group.name contains more stuff than just the name
                    found = True
                    break

            if not found:
                raise UnsupportedPlanningError('OpenRAVEAffineRetimer only supports untimed paths with affine DOFs. Found group: %s' % group.name)



        # Copy the input trajectory into the planning environment. This is
        # necessary for two reasons: (1) the input trajectory may be in another
        # environment and/or (2) the retimer modifies the trajectory in-place.
        output_traj = CopyTrajectory(path, env=self.env)

        # Compute the timing. This happens in-place.
        max_velocities = [robot.GetAffineTranslationMaxVels()[0],
                          robot.GetAffineTranslationMaxVels()[1],
                          robot.GetAffineRotationAxisMaxVels()[2]]
        max_accelerations = [3.*v for v in max_velocities]
        status = RetimeTrajectory(output_traj, max_velocities, max_accelerations,
                                  False)

        if status not in [ PlannerStatus.HasSolution,
                           PlannerStatus.InterruptedWithSolution ]:
            raise PlanningError('Retimer returned with status {0:s}.'.format(
                                str(status)))

        return output_traj
