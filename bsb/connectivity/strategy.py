from .. import config
from ..config import refs, types
from ..helpers import SortableByAfter
from ..functions import compute_intersection_slice
from ..models import ConnectivitySet
import abc

def _targetting_req(section):
    return "labels" not in section


@config.node
class HemitypeNode:
    cell_types = config.reflist(refs.cell_type_ref, required=_targetting_req)
    compartments = config.attr(type=types.list())
    labels = config.attr(type=types.list())


@config.dynamic
class ConnectionStrategy(abc.ABC, SortableByAfter):
    presynaptic = config.attr(type=HemitypeNode, required=True)
    postsynaptic = config.attr(type=HemitypeNode, required=True)
    after = config.reflist(refs.placement_ref)

    @classmethod
    def get_ordered(cls, objects):
        return objects.values()  # No sorting of connection types required.

    def get_after(self):
        return [] if not self.has_after() else self.after

    def has_after(self):
        return hasattr(self, "after")

    def create_after(self):
        self.after = []

    @abc.abstractmethod
    def connect(self, presyn_collection, postsyn_collection):
        pass

    def connect_cells(self, pre_type, post_type, src_locs, dest_locs, tag=None):
        pass

    def queue(self, pool, chunk_size):
        """
        Specifies how to queue this connectivity strategy into a job pool. Can
        be overridden, the default implementation asks each partition to chunk
        itself and creates 1 placement job per chunk.
        """
        # Reset jobs that we own
        self._queued_jobs = []
        # Get the queued jobs of all the strategies we depend on.
        deps = set(itertools.chain(*(strat._queued_jobs for strat in self.get_after())))
        for p in self.partitions:
            print("Queueing smth")
            chunks = p.to_chunks(chunk_size)
            for chunk in chunks:
                print("Queueing chunk")
                job = pool.queue_placement(self, chunk, chunk_size, deps=deps)
                self._queued_jobs.append(job)
