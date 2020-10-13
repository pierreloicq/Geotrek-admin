import os
import logging

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db.models import F, Value
from django.template.defaultfilters import slugify
from django.utils.translation import get_language, ugettext, ugettext_lazy as _
from django.urls import reverse

import simplekml
from mapentity.models import MapEntityMixin
from mapentity.serializers import plain_text

from geotrek.api.v2.functions import LineLocatePoint, Transform
from geotrek.authent.models import StructureRelated
from geotrek.core.models import Path, Topology, simplify_coords
from geotrek.common.utils import intersecting, classproperty
from geotrek.common.mixins import (PicturesMixin, PublishableMixin,
                                   PictogramMixin, OptionalPictogramMixin, NoDeleteManager)
from geotrek.common.models import Theme, ReservationSystem
from geotrek.maintenance.models import Intervention, Project
from geotrek.tourism import models as tourism_models

from .templatetags import trekking_tags

from colorfield.fields import ColorField

logger = logging.getLogger(__name__)


if 'geotrek.signage' in settings.INSTALLED_APPS:
    from geotrek.signage.models import Blade


class TrekOrderedChildManager(models.Manager):
    use_for_related_fields = True

    def get_queryset(self):
        # Select treks foreign keys by default
        qs = super(TrekOrderedChildManager, self).get_queryset().select_related('parent', 'child')
        # Exclude deleted treks
        return qs.exclude(parent__deleted=True).exclude(child__deleted=True)


class OrderedTrekChild(models.Model):
    parent = models.ForeignKey('Trek', related_name='trek_children', on_delete=models.CASCADE)
    child = models.ForeignKey('Trek', related_name='trek_parents', on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0, blank=True, null=True)

    objects = TrekOrderedChildManager()

    class Meta:
        ordering = ('parent__id', 'order')
        unique_together = (
            ('parent', 'child'),
        )


class Trek(Topology, StructureRelated, PicturesMixin, PublishableMixin, MapEntityMixin):
    topo_object = models.OneToOneField(Topology, parent_link=True, on_delete=models.CASCADE)
    departure = models.CharField(verbose_name=_("Departure"), max_length=128, blank=True,
                                 help_text=_("Departure description"))
    arrival = models.CharField(verbose_name=_("Arrival"), max_length=128, blank=True,
                               help_text=_("Arrival description"))
    description_teaser = models.TextField(verbose_name=_("Description teaser"), blank=True,
                                          help_text=_("A brief summary (map pop-ups)"))
    description = models.TextField(verbose_name=_("Description"), blank=True,
                                   help_text=_("Complete description"))
    ambiance = models.TextField(verbose_name=_("Ambiance"), blank=True,
                                help_text=_("Main attraction and interest"))
    access = models.TextField(verbose_name=_("Access"), blank=True,
                              help_text=_("Best way to go"))
    disabled_infrastructure = models.TextField(verbose_name=_("Disabled infrastructure"),
                                               blank=True, help_text=_("Any specific infrastructure"))
    duration = models.FloatField(verbose_name=_("Duration"), null=True, blank=True,
                                 help_text=_("In hours (1.5 = 1 h 30, 24 = 1 day, 48 = 2 days)"),
                                 validators=[MinValueValidator(0)])
    is_park_centered = models.BooleanField(verbose_name=_("Is in the midst of the park"),
                                           help_text=_("Crosses center of park"), default=False)
    advised_parking = models.CharField(verbose_name=_("Advised parking"), max_length=128, blank=True,
                                       help_text=_("Where to park"))
    parking_location = models.PointField(verbose_name=_("Parking location"),
                                         srid=settings.SRID, spatial_index=False, blank=True, null=True)
    public_transport = models.TextField(verbose_name=_("Public transport"), blank=True,
                                        help_text=_("Train, bus (see web links)"))
    advice = models.TextField(verbose_name=_("Advice"), blank=True,
                              help_text=_("Risks, danger, best period, ..."))
    themes = models.ManyToManyField(Theme, related_name="treks", blank=True, verbose_name=_("Themes"),
                                    help_text=_("Main theme(s)"))
    networks = models.ManyToManyField('TrekNetwork', related_name="treks", blank=True, verbose_name=_("Networks"),
                                      help_text=_("Hiking networks"))
    practice = models.ForeignKey('Practice', related_name="treks", on_delete=models.CASCADE,
                                 blank=True, null=True, verbose_name=_("Practice"))
    accessibilities = models.ManyToManyField('Accessibility', related_name="treks", blank=True,
                                             verbose_name=_("Accessibility"))
    route = models.ForeignKey('Route', related_name='treks', on_delete=models.CASCADE,
                              blank=True, null=True, verbose_name=_("Route"))
    difficulty = models.ForeignKey('DifficultyLevel', related_name='treks', on_delete=models.CASCADE,
                                   blank=True, null=True, verbose_name=_("Difficulty"))
    web_links = models.ManyToManyField('WebLink', related_name="treks", blank=True, verbose_name=_("Web links"),
                                       help_text=_("External resources"))
    related_treks = models.ManyToManyField('self', through='TrekRelationship',
                                           verbose_name=_("Related treks"), symmetrical=False,
                                           help_text=_("Connections between treks"),
                                           related_name='related_treks+')  # Hide reverse attribute
    information_desks = models.ManyToManyField(tourism_models.InformationDesk, related_name='treks',
                                               blank=True, verbose_name=_("Information desks"),
                                               help_text=_("Where to obtain information"))
    points_reference = models.MultiPointField(verbose_name=_("Points of reference"),
                                              srid=settings.SRID, spatial_index=False, blank=True, null=True)
    source = models.ManyToManyField('common.RecordSource',
                                    blank=True, related_name='treks',
                                    verbose_name=_("Source"))
    portal = models.ManyToManyField('common.TargetPortal',
                                    blank=True, related_name='treks',
                                    verbose_name=_("Portal"))
    eid = models.CharField(verbose_name=_("External id"), max_length=1024, blank=True, null=True)
    eid2 = models.CharField(verbose_name=_("Second external id"), max_length=1024, blank=True, null=True)
    pois_excluded = models.ManyToManyField('Poi', related_name='excluded_treks', verbose_name=_("Excluded POIs"),
                                           blank=True)
    reservation_system = models.ForeignKey(ReservationSystem, verbose_name=_("Reservation system"),
                                           on_delete=models.CASCADE, blank=True, null=True)
    reservation_id = models.CharField(verbose_name=_("Reservation ID"), max_length=1024,
                                      blank=True)

    capture_map_image_waitfor = '.poi_enum_loaded.services_loaded.info_desks_loaded.ref_points_loaded'

    class Meta:
        verbose_name = _("Trek")
        verbose_name_plural = _("Treks")
        ordering = ('name',)

    def __str__(self):
        return self.name

    def get_map_image_url(self):
        return reverse('trekking:trek_map_image', args=[str(self.pk), get_language()])

    def get_map_image_path(self):
        basefolder = os.path.join(settings.MEDIA_ROOT, 'maps')
        if not os.path.exists(basefolder):
            os.makedirs(basefolder)
        return os.path.join(basefolder, '%s-%s-%s.png' % (self._meta.model_name, self.pk, get_language()))

    def get_map_image_extent(self, srid=settings.API_SRID):
        extent = list(super(Trek, self).get_map_image_extent(srid))
        if self.parking_location:
            self.parking_location.transform(srid)
            extent[0] = min(extent[0], self.parking_location.x)
            extent[1] = min(extent[1], self.parking_location.y)
            extent[2] = max(extent[2], self.parking_location.x)
            extent[3] = max(extent[3], self.parking_location.y)
        if self.points_reference:
            self.points_reference.transform(srid)
            prextent = self.points_reference.extent
            extent[0] = min(extent[0], prextent[0])
            extent[1] = min(extent[1], prextent[1])
            extent[2] = max(extent[2], prextent[2])
            extent[3] = max(extent[3], prextent[3])
        for poi in self.published_pois:
            poi.geom.transform(srid)
            extent[0] = min(extent[0], poi.geom.x)
            extent[1] = min(extent[1], poi.geom.y)
            extent[2] = max(extent[2], poi.geom.x)
            extent[3] = max(extent[3], poi.geom.y)
        return extent

    @property
    def related(self):
        return self.related_treks.exclude(deleted=True).exclude(pk=self.pk).distinct()

    @classproperty
    def related_verbose_name(cls):
        return _("Related treks")

    @property
    def relationships(self):
        # Does not matter if a or b
        return TrekRelationship.objects.filter(trek_a=self)

    @property
    def published_relationships(self):
        return self.relationships.filter(trek_b__published=True)

    @property
    def poi_types(self):
        if settings.TREKKING_TOPOLOGY_ENABLED:
            # Can't use values_list and must add 'ordering' because of bug:
            # https://code.djangoproject.com/ticket/14930
            values = self.pois.values('ordering', 'type')
        else:
            values = self.pois.values('type')
        pks = [value['type'] for value in values]
        return POIType.objects.filter(pk__in=set(pks))

    @property
    def length_kilometer(self):
        return "%.1f" % (self.length_2d / 1000.0)

    @property
    def networks_display(self):
        return ', '.join([str(n) for n in self.networks.all()])

    @property
    def districts_display(self):
        return ', '.join([str(d) for d in self.districts])

    @property
    def themes_display(self):
        return ', '.join([str(n) for n in self.themes.all()])

    @property
    def information_desks_display(self):
        return ', '.join([str(n) for n in self.information_desks.all()])

    @property
    def accessibilities_display(self):
        return ', '.join([str(n) for n in self.accessibilities.all()])

    @property
    def web_links_display(self):
        return ', '.join([str(n) for n in self.web_links.all()])

    @property
    def city_departure(self):
        cities = self.published_cities
        return str(cities[0]) if len(cities) > 0 else ''

    def kml(self):
        """ Exports trek into KML format, add geometry as linestring and POI
        as place marks """
        kml = simplekml.Kml()
        # Main itinerary
        geom3d = self.geom_3d.transform(4326, clone=True)  # KML uses WGS84
        line = kml.newlinestring(name=self.name,
                                 description=plain_text(self.description),
                                 coords=simplify_coords(geom3d.coords))
        line.style.linestyle.color = simplekml.Color.red  # Red
        line.style.linestyle.width = 4  # pixels
        # Place marks
        for poi in self.published_pois:
            place = poi.geom_3d.transform(settings.API_SRID, clone=True)
            kml.newpoint(name=poi.name,
                         description=plain_text(poi.description),
                         coords=simplify_coords([place.coords]))
        return kml.kml()

    def has_geom_valid(self):
        """A trek should be a LineString, even if it's a loop.
        """
        return super(Trek, self).has_geom_valid() and self.geom.geom_type.lower() == 'linestring'

    @property
    def duration_pretty(self):
        return trekking_tags.duration(self.duration)

    @classproperty
    def duration_pretty_verbose_name(cls):
        return _("Formated duration")

    @classmethod
    def path_treks(cls, path):
        treks = cls.objects.existing().filter(aggregations__path=path)
        # The following part prevents conflict with default trek ordering
        # ProgrammingError: SELECT DISTINCT ON expressions must match initial ORDER BY expressions
        return treks.order_by('topo_object').distinct('topo_object')

    @classmethod
    def topology_treks(cls, topology):
        if settings.TREKKING_TOPOLOGY_ENABLED:
            qs = cls.overlapping(topology)
        else:
            area = topology.geom.buffer(settings.TREK_POI_INTERSECTION_MARGIN)
            qs = cls.objects.existing().filter(geom__intersects=area)
        return qs

    @classmethod
    def published_topology_treks(cls, topology):
        return cls.topology_treks(topology).filter(published=True)

    # Rando v1 compat
    @property
    def usages(self):
        return [self.practice] if self.practice else []

    @classmethod
    def get_create_label(cls):
        return _("Add a new trek")

    @property
    def parents(self):
        return Trek.objects.filter(trek_children__child=self, deleted=False)

    @property
    def parents_id(self):
        parents = self.trek_parents.values_list('parent__id', flat=True)
        return list(parents)

    @property
    def children(self):
        return Trek.objects.filter(trek_parents__parent=self, deleted=False).order_by('trek_parents__order')

    @property
    def children_id(self):
        """
        Get children IDs
        """
        children = self.trek_children.order_by('order')\
                                     .values_list('child__id',
                                                  flat=True)
        return children

    def previous_id_for(self, parent):
        children_id = list(parent.children_id)
        index = children_id.index(self.id)
        if index == 0:
            return None
        return children_id[index - 1]

    def next_id_for(self, parent):
        children_id = list(parent.children_id)
        index = children_id.index(self.id)
        if index == len(children_id) - 1:
            return None
        return children_id[index + 1]

    @property
    def previous_id(self):
        """
        Dict of parent -> previous child
        """
        return {parent.id: self.previous_id_for(parent) for parent in self.parents.filter(published=True, deleted=False)}

    @property
    def next_id(self):
        """
        Dict of parent -> next child
        """
        return {parent.id: self.next_id_for(parent) for parent in self.parents.filter(published=True, deleted=False)}

    def clean(self):
        """
        Custom model validation
        """
        if self.pk in self.trek_children.values_list('child__id', flat=True):
            raise ValidationError(_("Cannot use itself as child trek."))

    @property
    def prefixed_category_id(self):
        if settings.SPLIT_TREKS_CATEGORIES_BY_ITINERANCY and self.children.exists():
            return 'I'
        elif settings.SPLIT_TREKS_CATEGORIES_BY_PRACTICE and self.practice:
            return self.practice.prefixed_id
        else:
            return Practice.id_prefix

    def distance(self, to_cls):
        if self.practice and self.practice.distance is not None:
            return self.practice.distance
        else:
            return settings.TOURISM_INTERSECTION_MARGIN

    def is_public(self):
        for parent in self.parents:
            if parent.any_published:
                return True
        return self.any_published

    @property
    def picture_print(self):
        picture = super(Trek, self).picture_print
        if picture:
            return picture
        for poi in self.published_pois:
            picture = poi.picture_print
            if picture:
                return picture

    def save(self, *args, **kwargs):
        if self.pk is not None and kwargs.get('update_fields', None) is None:
            field_names = set()
            for field in self._meta.concrete_fields:
                if not field.primary_key and not hasattr(field, 'through'):
                    field_names.add(field.attname)
            old_trek = Trek.objects.get(pk=self.pk)
            if self.geom is not None and old_trek.geom.equals_exact(self.geom, tolerance=0.00001):
                field_names.remove('geom')
            if self.geom_3d is not None and old_trek.geom_3d.equals_exact(self.geom_3d, tolerance=0.00001):
                field_names.remove('geom_3d')
            return super(Trek, self).save(update_fields=field_names, *args, **kwargs)
        super(Trek, self).save(*args, **kwargs)

    @property
    def portal_display(self):
        return ', '.join([str(portal) for portal in self.portal.all()])

    @property
    def source_display(self):
        return ','.join([str(source) for source in self.source.all()])

    @property
    def extent(self):
        return self.geom.transform(settings.API_SRID, clone=True).extent if self.geom.extent else None

    @property
    def rando_url(self):
        if settings.SPLIT_TREKS_CATEGORIES_BY_PRACTICE and self.practice:
            category_slug = self.practice.slug
        else:
            category_slug = _('trek')
        return '{}/{}/'.format(category_slug, self.slug)

    @property
    def full_rando_url(self):
        try:
            return '{}/{}'.format(
                settings.ALLOWED_HOSTS[0],
                self.rando_url
            )
        except KeyError:
            # Do not display url if there is no ALLOWED_HOSTS
            return ""

    @property
    def meta_description(self):
        return plain_text(self.ambiance or self.description_teaser or self.description)[:500]

    def get_printcontext(self):
        maplayers = [
            settings.LEAFLET_CONFIG['TILES'][0][0],
        ]
        if settings.SHOW_SENSITIVE_AREAS_ON_MAP_SCREENSHOT:
            maplayers.append(ugettext("Sensitive area"))
        if settings.SHOW_POIS_ON_MAP_SCREENSHOT:
            maplayers.append(ugettext("POIs"))
        if settings.SHOW_SERVICES_ON_MAP_SCREENSHOT:
            maplayers.append(ugettext("Services"))
        if settings.SHOW_SIGNAGES_ON_MAP_SCREENSHOT:
            maplayers.append(ugettext("Signages"))
        if settings.SHOW_INFRASTRUCTURES_ON_MAP_SCREENSHOT:
            maplayers.append(ugettext("Infrastructures"))
        return {"maplayers": maplayers}


Path.add_property('treks', Trek.path_treks, _("Treks"))
Topology.add_property('treks', Trek.topology_treks, _("Treks"))
if settings.HIDE_PUBLISHED_TREKS_IN_TOPOLOGIES:
    Topology.add_property('published_treks', lambda self: [], _("Published treks"))
else:
    Topology.add_property('published_treks', lambda self: intersecting(Trek, self).filter(published=True), _("Published treks"))
Intervention.add_property('treks', lambda self: self.target.treks if self.target else [], _("Treks"))
Project.add_property('treks', lambda self: self.edges_by_attr('treks'), _("Treks"))
tourism_models.TouristicContent.add_property('treks', lambda self: intersecting(Trek, self), _("Treks"))
tourism_models.TouristicContent.add_property('published_treks', lambda self: intersecting(Trek, self).filter(published=True), _("Published treks"))
tourism_models.TouristicEvent.add_property('treks', lambda self: intersecting(Trek, self), _("Treks"))
tourism_models.TouristicEvent.add_property('published_treks', lambda self: intersecting(Trek, self).filter(published=True), _("Published treks"))
if 'geotrek.signage' in settings.INSTALLED_APPS:
    Blade.add_property('treks', lambda self: self.signage.treks, _("Treks"))
    Blade.add_property('published_treks', lambda self: self.signage.published_treks, _("Published treks"))


class TrekRelationshipManager(models.Manager):
    use_for_related_fields = True

    def get_queryset(self):
        # Select treks foreign keys by default
        qs = super(TrekRelationshipManager, self).get_queryset().select_related('trek_a', 'trek_b')
        # Exclude deleted treks
        return qs.exclude(trek_a__deleted=True).exclude(trek_b__deleted=True)


class TrekRelationship(models.Model):
    """
    Relationships between treks : symmetrical aspect is managed by a trigger that
    duplicates all couples (trek_a, trek_b)
    """
    has_common_departure = models.BooleanField(verbose_name=_("Common departure"), default=False)
    has_common_edge = models.BooleanField(verbose_name=_("Common edge"), default=False)
    is_circuit_step = models.BooleanField(verbose_name=_("Circuit step"), default=False)

    trek_a = models.ForeignKey(Trek, related_name="trek_relationship_a", on_delete=models.CASCADE)
    trek_b = models.ForeignKey(Trek, related_name="trek_relationship_b", verbose_name=_("Trek"), on_delete=models.CASCADE)

    objects = TrekRelationshipManager()

    class Meta:
        verbose_name = _("Trek relationship")
        verbose_name_plural = _("Trek relationships")
        unique_together = ('trek_a', 'trek_b')

    def __str__(self):
        return "%s <--> %s" % (self.trek_a, self.trek_b)

    @property
    def relation(self):
        return "%s %s%s%s" % (
            self.trek_b.name_display,
            _("Departure") if self.has_common_departure else '',
            _("Path") if self.has_common_edge else '',
            _("Circuit") if self.is_circuit_step else ''
        )

    @property
    def relation_display(self):
        return self.relation


class TrekNetwork(PictogramMixin):
    network = models.CharField(verbose_name=_("Name"), max_length=128)

    class Meta:
        verbose_name = _("Trek network")
        verbose_name_plural = _("Trek networks")
        ordering = ['network']

    def __str__(self):
        return self.network


class Practice(PictogramMixin):

    name = models.CharField(verbose_name=_("Name"), max_length=128)
    distance = models.IntegerField(verbose_name=_("Distance"), blank=True, null=True,
                                   help_text=_("Touristic contents and events will associate within this distance (meters)"))
    cirkwi = models.ForeignKey('cirkwi.CirkwiLocomotion', verbose_name=_("Cirkwi locomotion"), null=True, blank=True, on_delete=models.CASCADE)
    order = models.IntegerField(verbose_name=_("Order"), null=True, blank=True,
                                help_text=_("Alphabetical order if blank"))
    color = ColorField(verbose_name=_("Color"), default='#444444',
                       help_text=_("Color of the practice, only used in mobile."))  # To be implemented in Geotrek-rando

    id_prefix = 'T'

    class Meta:
        verbose_name = _("Practice")
        verbose_name_plural = _("Practices")
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def slug(self):
        return slugify(self.name) or str(self.pk)

    @property
    def prefixed_id(self):
        return '{prefix}{id}'.format(prefix=self.id_prefix, id=self.id)


class Accessibility(OptionalPictogramMixin):

    name = models.CharField(verbose_name=_("Name"), max_length=128)
    cirkwi = models.ForeignKey('cirkwi.CirkwiTag', verbose_name=_("Cirkwi tag"), null=True, blank=True, on_delete=models.CASCADE)

    id_prefix = 'A'

    class Meta:
        verbose_name = _("Accessibility")
        verbose_name_plural = _("Accessibilities")
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def prefixed_id(self):
        return '{prefix}{id}'.format(prefix=self.id_prefix, id=self.id)

    @property
    def slug(self):
        return slugify(self.name) or str(self.pk)


class Route(OptionalPictogramMixin):

    route = models.CharField(verbose_name=_("Name"), max_length=128)

    class Meta:
        verbose_name = _("Route")
        verbose_name_plural = _("Routes")
        ordering = ['route']

    def __str__(self):
        return self.route


class DifficultyLevel(OptionalPictogramMixin):

    """We use an IntegerField for id, since we want to edit it in Admin.
    This column is used to order difficulty levels, especially in public website
    where treks are filtered by difficulty ids.
    """
    id = models.IntegerField(primary_key=True)
    difficulty = models.CharField(verbose_name=_("Difficulty level"), max_length=128)
    cirkwi_level = models.IntegerField(verbose_name=_("Cirkwi level"), blank=True, null=True,
                                       help_text=_("Between 1 and 8"))
    cirkwi = models.ForeignKey('cirkwi.CirkwiTag', verbose_name=_("Cirkwi tag"), null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("Difficulty level")
        verbose_name_plural = _("Difficulty levels")
        ordering = ['id']

    def __str__(self):
        return self.difficulty

    def save(self, *args, **kwargs):
        """Manually auto-increment ids"""
        if not self.id:
            try:
                last = self.__class__.objects.all().order_by('-id')[0]
                self.id = last.id + 1
            except IndexError:
                self.id = 1
        super(DifficultyLevel, self).save(*args, **kwargs)


class WebLinkManager(models.Manager):
    def get_queryset(self):
        return super(WebLinkManager, self).get_queryset().select_related('category')


class WebLink(models.Model):

    name = models.CharField(verbose_name=_("Name"), max_length=128)
    url = models.URLField(verbose_name=_("URL"), max_length=2048)
    category = models.ForeignKey('WebLinkCategory', verbose_name=_("Category"),
                                 related_name='links', null=True, blank=True, on_delete=models.CASCADE)

    objects = WebLinkManager()

    class Meta:
        verbose_name = _("Web link")
        verbose_name_plural = _("Web links")
        ordering = ['name']

    def __str__(self):
        category = "%s - " % self.category.label if self.category else ""
        return "%s%s" % (category, self.name)

    @classmethod
    def get_add_url(cls):
        return reverse('trekking:weblink_add')


class WebLinkCategory(PictogramMixin):

    label = models.CharField(verbose_name=_("Label"), max_length=128)

    class Meta:
        verbose_name = _("Web link category")
        verbose_name_plural = _("Web link categories")
        ordering = ['label']

    def __str__(self):
        return "%s" % self.label


class POIManager(NoDeleteManager):
    def get_queryset(self):
        return super().get_queryset().select_related('type', 'structure')


class POI(StructureRelated, PicturesMixin, PublishableMixin, MapEntityMixin, Topology):

    topo_object = models.OneToOneField(Topology, parent_link=True, on_delete=models.CASCADE)
    description = models.TextField(verbose_name=_("Description"), blank=True, help_text=_("History, details,  ..."))
    type = models.ForeignKey('POIType', related_name='pois', verbose_name=_("Type"), on_delete=models.CASCADE)
    eid = models.CharField(verbose_name=_("External id"), max_length=1024, blank=True, null=True)

    class Meta:
        verbose_name = _("POI")
        verbose_name_plural = _("POI")

    # Override default manager
    objects = POIManager()

    # Do no check structure when selecting POIs to exclude
    check_structure_in_forms = False

    def __str__(self):
        return "%s (%s)" % (self.name, self.type)

    def save(self, *args, **kwargs):
        super(POI, self).save(*args, **kwargs)
        # Invalidate treks map
        for trek in self.treks.all():
            try:
                os.remove(trek.get_map_image_path())
            except OSError:
                pass

    @property
    def type_display(self):
        return str(self.type)

    @classmethod
    def path_pois(cls, path):
        return cls.objects.existing().filter(aggregations__path=path).distinct('pk')

    @classmethod
    def topology_pois(cls, topology):
        return cls.exclude_pois(cls.topology_all_pois(topology), topology)

    @classmethod
    def topology_all_pois(cls, topology):
        if settings.TREKKING_TOPOLOGY_ENABLED:
            qs = cls.overlapping(topology)
        else:
            object_geom = topology.geom.transform(settings.SRID, clone=True).buffer(settings.TREK_POI_INTERSECTION_MARGIN)
            qs = cls.objects.existing().filter(geom__intersects=object_geom)
            if topology.geom.geom_type == 'LineString':
                qs = qs.annotate(locate=LineLocatePoint(Transform(Value(topology.geom.ewkt,
                                                                        output_field=models.GeometryField()),
                                                                  settings.SRID),
                                                        Transform(F('geom'), settings.SRID)))
                qs = qs.order_by('locate')

        return qs

    @classmethod
    def published_topology_pois(cls, topology):
        return cls.topology_pois(topology).filter(published=True)

    def distance(self, to_cls):
        return settings.TOURISM_INTERSECTION_MARGIN

    @classmethod
    def exclude_pois(cls, qs, topology):
        try:
            return qs.exclude(pk__in=topology.trek.pois_excluded.values_list('pk', flat=True))
        except Trek.DoesNotExist:
            return qs

    @property
    def extent(self):
        return self.geom.transform(settings.API_SRID, clone=True).extent if self.geom else None


Path.add_property('pois', POI.path_pois, _("POIs"))
Topology.add_property('pois', POI.topology_pois, _("POIs"))
Topology.add_property('all_pois', POI.topology_all_pois, _("POIs"))
Topology.add_property('published_pois', POI.published_topology_pois, _("Published POIs"))
Intervention.add_property('pois', lambda self: self.target.pois if self.target else [], _("POIs"))
Project.add_property('pois', lambda self: self.edges_by_attr('pois'), _("POIs"))
tourism_models.TouristicContent.add_property('pois', lambda self: intersecting(POI, self), _("POIs"))
tourism_models.TouristicContent.add_property('published_pois', lambda self: intersecting(POI, self).filter(published=True), _("Published POIs"))
tourism_models.TouristicEvent.add_property('pois', lambda self: intersecting(POI, self), _("POIs"))
tourism_models.TouristicEvent.add_property('published_pois', lambda self: intersecting(POI, self).filter(published=True), _("Published POIs"))
if 'geotrek.signage' in settings.INSTALLED_APPS:
    Blade.add_property('pois', lambda self: self.signage.pois, _("POIs"))
    Blade.add_property('published_pois', lambda self: self.signage.published_pois, _("Published POIs"))


class POIType(PictogramMixin):

    label = models.CharField(verbose_name=_("Label"), max_length=128)
    cirkwi = models.ForeignKey('cirkwi.CirkwiPOICategory', verbose_name=_("Cirkwi POI category"), null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("POI type")
        verbose_name_plural = _("POI types")
        ordering = ['label']

    def __str__(self):
        return self.label


class ServiceType(PictogramMixin, PublishableMixin):

    practices = models.ManyToManyField('Practice', related_name="services",
                                       blank=True,
                                       verbose_name=_("Practices"))

    class Meta:
        verbose_name = _("Service type")
        verbose_name_plural = _("Service types")
        ordering = ['name']

    def __str__(self):
        return self.name


class ServiceManager(NoDeleteManager):
    def get_queryset(self):
        return super().get_queryset().select_related('type', 'structure')


class Service(StructureRelated, MapEntityMixin, Topology):

    topo_object = models.OneToOneField(Topology, parent_link=True,
                                       on_delete=models.CASCADE)
    type = models.ForeignKey('ServiceType', related_name='services', verbose_name=_("Type"), on_delete=models.CASCADE)
    eid = models.CharField(verbose_name=_("External id"), max_length=1024, blank=True, null=True)

    class Meta:
        verbose_name = _("Service")
        verbose_name_plural = _("Services")

    # Override default manager
    objects = ServiceManager()

    def __str__(self):
        return str(self.type)

    @property
    def name(self):
        return self.type.name

    @property
    def name_display(self):
        s = '<a data-pk="%s" href="%s" title="%s">%s</a>' % (self.pk,
                                                             self.get_detail_url(),
                                                             self.name,
                                                             self.name)
        if self.type.published:
            s = '<span class="badge badge-success" title="%s">&#x2606;</span> ' % _("Published") + s
        elif self.type.review:
            s = '<span class="badge badge-warning" title="%s">&#x2606;</span> ' % _("Waiting for publication") + s
        return s

    @classproperty
    def name_verbose_name(cls):
        return _("Type")

    @property
    def type_display(self):
        return str(self.type)

    @classmethod
    def path_services(cls, path):
        return cls.objects.existing().filter(aggregations__path=path).distinct('pk')

    @classmethod
    def topology_services(cls, topology):
        if settings.TREKKING_TOPOLOGY_ENABLED:
            qs = cls.overlapping(topology)
        else:
            area = topology.geom.buffer(settings.TREK_POI_INTERSECTION_MARGIN)
            qs = cls.objects.existing().filter(geom__intersects=area)
        if isinstance(topology, Trek):
            qs = qs.filter(type__practices=topology.practice)
        return qs

    @classmethod
    def published_topology_services(cls, topology):
        return cls.topology_services(topology).filter(type__published=True)

    def distance(self, to_cls):
        return settings.TOURISM_INTERSECTION_MARGIN


Path.add_property('services', Service.path_services, _("Services"))
Topology.add_property('services', Service.topology_services, _("Services"))
Topology.add_property('published_services', Service.published_topology_services, _("Published Services"))
Intervention.add_property('services', lambda self: self.target.services if self.target else [], _("Services"))
Project.add_property('services', lambda self: self.edges_by_attr('services'), _("Services"))
tourism_models.TouristicContent.add_property('services', lambda self: intersecting(Service, self), _("Services"))
tourism_models.TouristicContent.add_property('published_services', lambda self: intersecting(Service, self).filter(published=True), _("Published Services"))
tourism_models.TouristicEvent.add_property('services', lambda self: intersecting(Service, self), _("Services"))
tourism_models.TouristicEvent.add_property('published_services', lambda self: intersecting(Service, self).filter(published=True), _("Published Services"))
if 'geotrek.signage' in settings.INSTALLED_APPS:
    Blade.add_property('services', lambda self: self.signage.services, _("Services"))
    Blade.add_property('published_services', lambda self: self.signage.published_pois, _("Published Services"))
