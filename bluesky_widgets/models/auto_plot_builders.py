from abc import abstractproperty
from collections import defaultdict

from ..utils.dict_view import DictView
from .utils import run_is_live_and_not_completed
from .plot_builders import RecentLines
from .plot_specs import FigureSpecList
from ._heuristics import infer_lines_to_plot


class Auto:
    """
    Base class for auto-plotters

    EXPERIMENTAL! This is very like to change in a backward-incompatible way.
    """

    @abstractproperty
    def _plot_builder(self):
        """
        Plot-builder model, such as RecentLines.

        Expected to implement:

        * add_run(run, pinned)
        * discard_run(run)
        * figure
        * max_runs
        """
        pass

    @abstractproperty
    def _heuristic(self):
        """
        Callable that suggests what to plot

        Expected signature::

            f(run) -> List[Dict]

        where Dict is kwargs accepted by _plot_builder.__init__.
        """
        pass

    def __init__(self, max_runs):
        self.figures = FigureSpecList()
        self._max_runs = max_runs

        # Map key like ((x, y), stream_name) to RecentLines instance so configured.
        self._key_to_instance = {}
        # Map FigureSpec UUID to key like ((x, y), stream_name)
        self._figure_to_key = {}
        # Track inactive instances/figures which are no longer being updated
        # with new Runs. Structure is a dict-of-dicts like:
        # {key: {figure_uuid: instance, ...}, ...}
        self._inactive_instances = defaultdict(dict)
        self.figures.events.removed.connect(self._on_figure_removed)

    @property
    def keys_to_figures(self):
        "Read-only mapping of each key to the active instance."
        return DictView({v: k for k, v in self._figure_to_key.items()})

    def new_instance_for_key(self, key):
        """
        Make a new instance for a key.

        If there is an existing one the instance and figure will remain but
        will no longer be updated with new Runs. Those will go to a new
        instance and figure, created here.
        """
        old_instance = self._key_to_instance.pop(key, None)
        if old_instance is not None:
            self._inactive_instances[key][old_instance.figure.uuid] = old_instance
        instance = self._plot_builder(max_runs=self.max_runs, **dict(key)
        )
        self._key_to_instance[key] = instance
        self._figure_to_key[instance.figure.uuid] = key
        self.figures.append(instance.figure)
        return instance

    def add_run(self, run, pinned=False):
        """
        Add a Run.

        Parameters
        ----------
        run : BlueskyRun
        pinned : Boolean
            If True, retain this Run until it is removed by the user.
        """
        for stream_name in run:
            self._handle_stream(run, stream_name, pinned)
        if run_is_live_and_not_completed(run):
            # Listen for additional streams.
            run.events.new_stream.connect(
                lambda event: self._handle_stream(run, event.name, pinned)
            )

    def discard_run(self, run):
        """
        Discard a Run, including any pinned and unpinned.

        If the Run is not present, this will return silently. Also,
        note that this only affect "active" plots that are currently
        receive new runs. Inactive ones will be left as they are.

        Parameters
        ----------
        run : BlueskyRun
        """
        for instance in self._key_to_instance.values():
            instance.discard_run(run)

    def _handle_stream(self, run, stream_name, pinned):
        "This examines a stream and adds this run to instances."
        for suggestion in infer_lines_to_plot(run, run[stream_name]):
            # Make a hashable `key` out of the dict `suggestions`.
            key = tuple(suggestion.items())
            try:
                instance = self._key_to_instance[key]
            except KeyError:
                instance = self.new_instance_for_key(key)
            instance.add_run(run, pinned=pinned)

    def _on_figure_removed(self, event):
        """
        A figure was removed from self.figures.

        Remove the relevant instance.
        """
        figure = event.item
        try:
            key = self._figure_to_key.pop(figure.uuid)
        except KeyError:
            # This figure belongs to an inactive instance.
            del self._inactive_instances[key][figure.uuid]

        else:
            self._key_to_instance.pop(key)

    @property
    def max_runs(self):
        return self._max_runs

    @max_runs.setter
    def max_runs(self, value):
        self._max_runs = value
        for instance in self._key_to_instance.values():
            instance.max_runs = value


class AutoRecentLines(Auto):
    """
    Automatically guess useful lines to plot. Show the last N runs (per figure).

    Parameters
    ----------
    max_runs : int
        Number of Runs to plot at once, per figure

    Attributes
    ----------
    figures : FigureSpecList[FigureSpec]
    max_runs : int
        Number of Runs to plot at once. This may be changed at any point.
        (Note: Increasing it will not restore any Runs that have already been
        removed, but it will allow more new Runs to be added.)
    keys_to_figures : dict
        Read-only mapping of each key to the active RecentLines instance.

    Examples
    --------
    >>> model = AutoRecentLines(3)
    >>> from bluesky_widgets.jupyter.figures import JupyterFigures
    >>> view = JupyterFigures(model.figures)
    >>> model.add_run(run)
    >>> model.add_run(another_run, pinned=True)
    """

    @property
    def _plot_builder(self):
        return RecentLines

    @property
    def _heuristic(self):
        return infer_lines_to_plot
