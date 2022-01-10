import numpy as np, random
from .morphologies import Morphology as BaseMorphology
from .helpers import (
    SortableByAfter,
)
from .exceptions import *


class CellType(SortableByAfter):
    """
    A CellType represents a population of cells.
    """

    def __init__(self, name):
        self.name = name
        self.relay = False

    def validate(self):
        """
        Check whether this CellType is valid to be used in the simulation.
        """
        pass

    def initialise(self, scaffoldInstance):
        self.scaffold = scaffoldInstance
        self.validate()

    def set_morphology(self, morphology):
        """
        Set the Morphology class for this cell type.

        :param morphology: Defines the geometrical constraints for the axon and dendrites of the cell type.
        :type morphology: Instance of a subclass of scaffold.morphologies.Morphology
        """
        if not issubclass(type(morphology), BaseMorphology):
            raise ClassError(
                "Only subclasses of scaffold.morphologies.Morphology can be used as cell morphologies."
            )
        self.morphology = morphology

    def place(self):
        """
        Place this cell type.
        """
        self.scaffold.place_cell_type(self)

    def list_all_morphologies(self):
        """
        Return a list of all the morphology identifiers that can represent
        this cell type in the simulation volume.
        """
        if not hasattr(self, "morphology") or not hasattr(
            self.morphology, "detailed_morphologies"
        ):
            return []
        morphology_config = self.morphology.detailed_morphologies
        # TODO: More selection mechanisms like tags
        if "names" in morphology_config:
            m_names = morphology_config["names"]
            return m_names.copy()
        else:
            raise NotImplementedError(
                "Detailed morphologies can currently only be selected by name."
            )

    def get_placement_set(self):
        return self.scaffold.get_placement_set(self)


class Layer:
    def scale_to_reference(self):
        """
        Compute scaled layer volume

        To compute layer thickness, we scale the current layer to the combined volume
        of the reference layers. A ratio between the dimension can be specified to
        alter the shape of the layer. By default equal ratios are used and a cubic
        layer is obtained (given by `dimension_ratios`).

        The volume of the current layer (= X*Y*Z) is scaled with respect to the volume
        of reference layers by a factor `volume_scale`, so:

        X*Y*Z = volume_reference_layers / volume_scale                [A]

        Supposing that the current layer dimensions (X,Y,Z) are each one depending on
        the dimension Y according to `dimension_ratios`, we obtain:

        X*Y*Z = (Y*dimension_ratios[0] * Y * (Y*dimension_ratios[2])  [B]
        X*Y*Z = (Y^3) * prod(dimension_ratios)                        [C]

        Therefore putting together [A] and [C]:
        (Y^3) * prod(dimension_ratios) = volume_reference_layers / volume_scale

        from which we derive the normalized_size Y, according to the following
        formula:

        Y = cubic_root((volume_reference_layers * volume_scale) / prod(dimension_ratios))
        """
        volume_reference_layers = np.sum(
            list(map(lambda layer: layer.volume, self.reference_layers))
        )
        # Compute volume: see docstring.
        normalized_size = pow(
            volume_reference_layers * self.volume_scale / np.prod(self.dimension_ratios),
            1 / 3,
        )
        # Apply the normalized size with their ratios to each dimension
        self.dimensions = np.multiply(
            np.repeat(normalized_size, 3), self.dimension_ratios
        )


class Resource:
    def __init__(self, handler, path):
        self._handler = handler
        self._path = path

    def get_dataset(self, selector=(), dtype=None):
        with self._handler.load("r") as f:
            if not self._path in f():
                raise DatasetNotFoundError(
                    "Dataset '{}' not found in '{}'.".format(
                        self._path, self._handler.file
                    )
                )
            d = f()[self._path][selector]
            if dtype:
                d = d.astype(dtype)
            return d

    @property
    def attributes(self):
        with self._handler.open("r") as f:
            return dict(f()[self._path].attrs)

    def get_attribute(self, name):
        attrs = self.attributes
        if name not in attrs:
            raise AttributeMissingError(
                "Attribute '{}' not found in '{}'".format(name, self._path)
            )
        return attrs[name]

    def exists(self):
        with self._handler.open("r") as f:
            return self._path in f()

    def unmap(self, selector=(), mapping=lambda m, x: m[x], data=None):
        if data is None:
            data = self.get_dataset(selector)
        map = self.get_attribute("map")
        unmapped = []
        for record in data:
            unmapped.append(mapping(map, record))
        return np.array(unmapped)

    def unmap_one(self, data, mapping=None):
        if mapping is None:
            return self.unmap(data=[data])
        else:
            return self.unmap(data=[data], mapping=mapping)

    def __iter__(self):
        return iter(self.get_dataset())

    @property
    def shape(self):
        with self._handler.open("r") as f:
            return f()[self._path].shape


class Connection:
    def __init__(
        self,
        from_id,
        to_id,
        from_compartment=None,
        to_compartment=None,
        from_morphology=None,
        to_morphology=None,
    ):
        self.from_id = from_id
        self.to_id = to_id
        if (
            from_compartment is not None
            or to_compartment is not None
            or from_morphology is not None
            or to_morphology is not None
        ):
            # If one of the 4 arguments for a detailed connection is given, all 4 are required.
            if (
                from_compartment is None
                or to_compartment is None
                or from_morphology is None
                or to_morphology is None
            ):
                raise RuntimeError(
                    "Insufficient arguments given to Connection constructor."
                    + " If one of the 4 arguments for a detailed connection is given, all 4 are required."
                )
            self.from_compartment = from_morphology.compartments[from_compartment]
            self.to_compartment = to_morphology.compartments[to_compartment]


class ConnectivitySet(Resource):
    """
    Connectivity sets store connections.
    """

    def __init__(self, handler, tag):
        super().__init__(handler, "/cells/connections/" + tag)
        if not self.exists():
            raise DatasetNotFoundError("ConnectivitySet '{}' does not exist".format(tag))
        self.scaffold = handler.scaffold
        self.tag = tag
        self.compartment_set = Resource(handler, "/cells/connection_compartments/" + tag)
        self.morphology_set = Resource(handler, "/cells/connection_morphologies/" + tag)

    @property
    def connections(self):
        """
        Return a list of :class:`Intersections <.models.Connection>`. Connections
        contain pre- & postsynaptic identifiers.
        """
        return [Connection(c[0], c[1]) for c in self.get_dataset()]

    @property
    def from_identifiers(self):
        """
        Return a list with the presynaptic identifier of each connection.
        """
        return self.get_dataset(dtype=int)[:, 0]

    @property
    def to_identifiers(self):
        """
        Return a list with the postsynaptic identifier of each connection.
        """
        return self.get_dataset(dtype=int)[:, 1]

    @property
    def intersections(self):
        """
        Return a list of :class:`Intersections <.models.Connection>`. Intersections
        contain pre- & postsynaptic identifiers and the intersecting compartments.
        """
        if not self.compartment_set.exists():
            raise MissingMorphologyError(
                "No intersection/morphology information for the '{}' connectivity set.".format(
                    self.tag
                )
            )
        else:
            return self.get_intersections()

    def get_intersections(self):
        intersections = []
        morphos = {}

        def _cache_morpho(id):
            # Keep a cache of the morphologies so that all morphologies with the same
            # id refer to the same object, and so that they aren't redundandly loaded.
            id = int(id)
            if not id in morphos:
                name = self.morphology_set.unmap_one(id)[0]
                if isinstance(name, bytes):
                    name = name.decode("UTF-8")
                morphos[id] = self.scaffold.morphology_repository.load(name)

        cells = self.get_dataset()
        for cell_ids, comp_ids, morpho_ids in zip(
            cells, self.compartment_set.get_dataset(), self.morphology_set.get_dataset()
        ):
            from_morpho_id = int(morpho_ids[0])
            to_morpho_id = int(morpho_ids[1])
            # Load morphologies from the map if they're not in the cache yet
            _cache_morpho(from_morpho_id)
            _cache_morpho(to_morpho_id)
            # Append the intersection with a new connection
            intersections.append(
                Connection(
                    *cell_ids,  # zipped dataset: from id & to id
                    *comp_ids,  # zipped morphologyset: from comp & to comp
                    morphos[from_morpho_id],  # cached: 'from' TrueMorphology
                    morphos[to_morpho_id]  # cached: 'to' TrueMorphology
                )
            )
        return intersections

    def get_divergence_list(self):
        presynaptic_type = self.get_presynaptic_types()[0]
        placement_set = self.scaffold.get_placement_set(presynaptic_type)
        unique_connections = np.unique(self.get_dataset(), axis=0)
        _, divergence_list = np.unique(unique_connections[:, 0], return_counts=True)
        return np.concatenate(
            (divergence_list, np.zeros(len(placement_set) - len(divergence_list)))
        )

    @property
    def divergence(self):
        divergence_list = self.get_divergence_list()
        if len(divergence_list) == 0:
            return 0
        return np.mean(divergence_list)

    def get_convergence_list(self):
        postsynaptic_type = self.get_postsynaptic_types()[0]
        placement_set = self.scaffold.get_placement_set(postsynaptic_type)
        unique_connections = np.unique(self.get_dataset(), axis=0)
        _, convergence_list = np.unique(unique_connections[:, 1], return_counts=True)
        return np.concatenate(
            (convergence_list, np.zeros(len(placement_set) - len(convergence_list)))
        )

    @property
    def convergence(self):
        convergence_list = self.get_convergence_list()
        if len(convergence_list) == 0:
            return 0
        return np.mean(convergence_list)

    def __iter__(self):
        if self.compartment_set.exists():
            return self.intersections
        else:
            return self.connections

    def __len__(self):
        return self.shape[0]

    @property
    def meta(self):
        """
        Retrieve the metadata associated with this connectivity set. Returns
        ``None`` if the connectivity set does not exist.

        :return: Metadata
        :rtype: dict
        """
        return self.attributes

    @property
    def connection_types(self):
        """
        Return all the ConnectionStrategies that contributed to the creation of this
        connectivity set.
        """
        # Get list of contributing types
        type_list = self.attributes["connection_types"]
        # Map contributing type names to contributing types
        return list(map(lambda name: self.scaffold.get_connection_type(name), type_list))

    def _get_cell_types(self, key="from"):
        meta = self.meta
        if key + "_cell_types" in meta:
            cell_types = set()
            for name in meta[key + "_cell_types"]:
                cell_types.add(self.scaffold.get_cell_type(name))
            return list(cell_types)
        cell_types = set()
        for connection_type in self.connection_types:
            cell_types |= set(connection_type.__dict__[key + "_cell_types"])
        return list(cell_types)

    def get_presynaptic_types(self):
        """
        Return a list of the presynaptic cell types found in this set.
        """
        return self._get_cell_types(key="from")

    def get_postsynaptic_types(self):
        """
        Return a list of the postsynaptic cell types found in this set.
        """
        return self._get_cell_types(key="to")
