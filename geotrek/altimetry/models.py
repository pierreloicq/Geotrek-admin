import os

from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import get_language, ugettext_lazy as _
from django.urls import reverse

from mapentity.helpers import is_file_uptodate, convertit_download, smart_urljoin
from .helpers import AltimetryHelper


class Elevation(models.Model):
    id = models.AutoField(primary_key=True, db_column='rid')
    rast = models.RasterField()

    class Meta:
        db_table = 'mnt'


class AltimetryMixin(models.Model):
    # Computed values (managed at DB-level with triggers)
    geom_3d = models.GeometryField(dim=3, srid=settings.SRID, spatial_index=False,
                                   editable=False, null=True, default=None)
    length = models.FloatField(editable=False, default=0.0, null=True, blank=True, verbose_name=_("3D Length"))
    ascent = models.IntegerField(editable=False, default=0, null=True, blank=True, verbose_name=_("Ascent"))
    descent = models.IntegerField(editable=False, default=0, null=True, blank=True, verbose_name=_("Descent"))
    min_elevation = models.IntegerField(editable=False, default=0, null=True, blank=True,
                                        verbose_name=_("Minimum elevation"))
    max_elevation = models.IntegerField(editable=False, default=0, null=True, blank=True,
                                        verbose_name=_("Maximum elevation"))
    slope = models.FloatField(editable=False, null=True, blank=True, default=0.0,
                              verbose_name=_("Slope"))

    COLUMNS = ['length', 'ascent', 'descent', 'min_elevation', 'max_elevation', 'slope']

    class Meta:
        abstract = True

    @property
    def length_display(self):
        return round(self.length, 1)

    def reload(self, fromdb):
        """Reload fields computed at DB-level (triggers)
        """
        self.geom_3d = fromdb.geom_3d
        self.length = fromdb.length
        self.ascent = fromdb.ascent
        self.descent = fromdb.descent
        self.min_elevation = fromdb.min_elevation
        self.max_elevation = fromdb.max_elevation
        self.slope = fromdb.slope
        return self

    def get_elevation_profile(self):
        return AltimetryHelper.elevation_profile(self.geom_3d)

    def get_elevation_area(self):
        return AltimetryHelper.elevation_area(self.geom)

    def get_elevation_limits(self):
        return AltimetryHelper.altimetry_limits(self.get_elevation_profile())

    def get_elevation_profile_svg(self, language=None):
        return AltimetryHelper.profile_svg(self.get_elevation_profile(), language)

    def get_elevation_chart_url(self, language=None):
        """Generic url. Will fail if there is no such url defined
        for the required model (see core.Path and trekking.Trek)
        """
        app_label = self._meta.app_label
        model_name = self._meta.model_name
        if not language:
            language = get_language()
        return reverse('%s:%s_profile_svg' % (app_label, model_name), kwargs={'lang': language, 'pk': self.pk})

    def get_elevation_chart_url_png(self, language=None):
        """Path to the PNG version of elevation chart. Relative to MEDIA_URL/MEDIA_ROOT.
        """
        if not language:
            language = get_language()
        return os.path.join('profiles', '%s-%s-%s.png' % (self._meta.model_name, self.pk, language))

    def get_elevation_chart_path(self, language=None):
        """Path to the PNG version of elevation chart.
        """
        if not language:
            language = get_language()
        basefolder = os.path.join(settings.MEDIA_ROOT, 'profiles')
        if not os.path.exists(basefolder):
            os.mkdir(basefolder)
        return os.path.join(basefolder, '%s-%s-%s.png' % (self._meta.model_name, self.pk, language))

    def prepare_elevation_chart(self, language, rooturl):
        """Converts SVG elevation URI to PNG on disk.
        """
        from .views import HttpSVGResponse
        path = self.get_elevation_chart_path(language)
        # Do nothing if image is up-to-date
        if is_file_uptodate(path, self.date_update):
            return False
        # Download converted chart as png using convertit
        source = smart_urljoin(rooturl, self.get_elevation_chart_url(language))
        convertit_download(source,
                           path,
                           from_type=HttpSVGResponse.content_type,
                           to_type='image/png',
                           headers={'Accept-Language': language})
        return True
