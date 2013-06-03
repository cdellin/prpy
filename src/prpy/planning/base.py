class PlanningError(Exception):
    pass

class UnsupportedPlanningError(PlanningError):
    pass

class Planner(object):
    methods = set()

    @classmethod
    def register_type(cls, method_name):
        def plan_wrapper(self, *args, **kw_args):
            return self.plan(method_name, args, kw_args)

        cls.methods.add(method_name)
        plan_wrapper.__name__ = method_name
        setattr(cls, method_name, plan_wrapper)

    def plan(self, method, args, kw_args):
        try:
            method = getattr(self, method)
            print 'Calling %s' % method
            return method(*args, **kw_args)
        except AttributeError:
            raise UnsupportedPlanningError

    def bind(self, instance, executer=None):
        from functools import wraps

        # The default executer is simply a wrapper for the planner.
        if executer is None:
            def executer(planning_method, args, kw_args):
                return planning_method(*args, **kw_args)

        def create_wrapper(planning_method):
            @wraps(planning_method)
            def wrapper_method(*args, **kw_args):
                return executer(planning_method, args, kw_args)

            return wrapper_method

        for method_name in self.__class__.methods:
            planning_method = getattr(self, method_name)
            wrapper_method = create_wrapper(planning_method)
            setattr(instance, method_name, wrapper_method)

class Sequence(Planner):
    def __init__(self, *planners):
        self._planners = planners

    def plan(self, method, args, kw_args):
        for planner in self._planners:
            try:
                return planner.plan(method, args, kw_args)
            except PlanningError, e:
                pass

        raise PlanningError

class Ranked(Planner):
    def __init__(self, *planners):
        self._planners = planners

    def plan(self, method, args, kw_args):
        pass

class Fastest(Planner):
    def __init__(self, *planners):
        self._planners = planners

    def plan(self, method, args, kw_args):
        pass
