from django.conf import settings
from django.contrib.gis.db.models.functions import Transform
from django.http import HttpResponse

import logging
from mapentity.views import (MapEntityLayer, MapEntityList, MapEntityJsonList, MapEntityFormat, MapEntityViewSet,
                             MapEntityDetail, MapEntityDocument, MapEntityCreate, MapEntityUpdate, MapEntityDelete)

from geotrek.authent.decorators import same_structure_required
from geotrek.common.views import FormsetMixin
from geotrek.core.models import AltimetryMixin

from geotrek.signage.filters import SignageFilterSet, BladeFilterSet
from geotrek.signage.forms import SignageForm, BladeForm, LineFormset
from geotrek.signage.models import Signage, Blade
from geotrek.signage.serializers import (SignageSerializer, BladeSerializer,
                                         SignageGeojsonSerializer, BladeGeojsonSerializer,
                                         CSVBladeSerializer, ZipBladeShapeSerializer)

from rest_framework import permissions as rest_permissions


logger = logging.getLogger(__name__)


class LineMixin(FormsetMixin):
    context_name = 'line_formset'
    formset_class = LineFormset


class SignageLayer(MapEntityLayer):
    queryset = Signage.objects.existing()
    properties = ['name', 'published']


class SignageList(MapEntityList):
    queryset = Signage.objects.existing()
    filterform = SignageFilterSet
    columns = ['id', 'name', 'code', 'type', 'condition']


class SignageJsonList(MapEntityJsonList, SignageList):
    pass


class SignageFormatList(MapEntityFormat, SignageList):
    columns = [
        'id', 'structure', 'name', 'code', 'type', 'condition', 'description',
        'implantation_year', 'published', 'date_insert',
        'date_update', 'cities', 'districts', 'areas', 'lat_value', 'lng_value',
        'printed_elevation', 'sealing', 'manager',
    ] + AltimetryMixin.COLUMNS


class SignageDetail(MapEntityDetail):
    queryset = Signage.objects.existing()

    def get_context_data(self, *args, **kwargs):
        context = super(SignageDetail, self).get_context_data(*args, **kwargs)
        context['can_edit'] = self.get_object().same_structure(self.request.user)
        return context


class SignageDocument(MapEntityDocument):
    model = Signage


class SignageCreate(MapEntityCreate):
    model = Signage
    form_class = SignageForm


class SignageUpdate(MapEntityUpdate):
    queryset = Signage.objects.existing()
    form_class = SignageForm

    @same_structure_required('signage:signage_detail')
    def dispatch(self, *args, **kwargs):
        return super(SignageUpdate, self).dispatch(*args, **kwargs)


class SignageDelete(MapEntityDelete):
    model = Signage

    @same_structure_required('signage:signage_detail')
    def dispatch(self, *args, **kwargs):
        return super(SignageDelete, self).dispatch(*args, **kwargs)


class SignageViewSet(MapEntityViewSet):
    model = Signage
    serializer_class = SignageSerializer
    geojson_serializer_class = SignageGeojsonSerializer
    permission_classes = [rest_permissions.DjangoModelPermissionsOrAnonReadOnly]

    def get_queryset(self):
        return Signage.objects.existing().filter(published=True).annotate(api_geom=Transform("geom", settings.API_SRID))


class BladeDetail(MapEntityDetail):
    queryset = Blade.objects.all()

    def get_context_data(self, *args, **kwargs):
        context = super(BladeDetail, self).get_context_data(*args, **kwargs)
        context['can_edit'] = self.get_object().signage.same_structure(self.request.user)
        return context


class BladeDocument(MapEntityDocument):
    model = Blade


class BladeCreate(LineMixin, MapEntityCreate):
    model = Blade
    form_class = BladeForm

    def get_signage(self):
        pk_infra = self.request.GET.get('signage')
        if pk_infra:
            try:
                return Signage.objects.existing().get(pk=pk_infra)
            except Signage.DoesNotExist:
                logger.warning("Intervention on unknown infrastructure %s" % pk_infra)
        return None

    def get_initial(self):
        """
        Returns the initial data to use for forms on this view.
        """
        initial = super(BladeCreate, self).get_initial()
        signage = self.get_signage()
        initial['signage'] = signage
        return initial

    def get_success_url(self):
        return self.get_signage().get_detail_url()


class BladeUpdate(LineMixin, MapEntityUpdate):
    queryset = Blade.objects.all()
    form_class = BladeForm

    @same_structure_required('signage:blade_detail')
    def dispatch(self, *args, **kwargs):
        return super(BladeUpdate, self).dispatch(*args, **kwargs)


class BladeDelete(MapEntityDelete):
    model = Blade

    @same_structure_required('signage:blade_detail')
    def dispatch(self, *args, **kwargs):
        return super(BladeDelete, self).dispatch(*args, **kwargs)

    def delete(self, request, *args, **kwargs):
        self.signage = self.get_object().signage
        return super(BladeDelete, self).delete(request, args, kwargs)

    def get_success_url(self):
        return self.signage.get_detail_url()


class BladeViewSet(MapEntityViewSet):
    model = Blade
    serializer_class = BladeSerializer
    geojson_serializer_class = BladeGeojsonSerializer
    queryset = Blade.objects.all()
    permission_classes = [rest_permissions.DjangoModelPermissionsOrAnonReadOnly]

    def get_queryset(self):
        return Blade.objects.all().annotate(api_geom=Transform("signage__geom", settings.API_SRID))


class BladeList(MapEntityList):
    queryset = Blade.objects.all()
    filterform = BladeFilterSet
    columns = ['id', 'number', 'direction', 'type', 'color']


class BladeJsonList(MapEntityJsonList, BladeList):
    pass


class BladeLayer(MapEntityLayer):
    queryset = Blade.objects.all()
    properties = ['number']


class BladeFormatList(MapEntityFormat, BladeList):
    columns = [
        'id', 'city', 'signage', 'printedelevation', 'bladecode', 'type', 'color', 'direction', 'condition',
        'coordinates'
    ]
    columns_line = ['number', 'text', 'distance_pretty', 'time_pretty', 'pictogram_name']

    def csv_view(self, request, context, **kwargs):
        serializer = CSVBladeSerializer()
        response = HttpResponse(content_type='text/csv')
        serializer.serialize(queryset=self.get_queryset(), stream=response,
                             model=self.get_model(), fields=self.columns, line_fields=self.columns_line,
                             ensure_ascii=True)
        return response

    def shape_view(self, request, context, **kwargs):
        serializer = ZipBladeShapeSerializer()
        response = HttpResponse(content_type='application/zip')
        serializer.serialize(queryset=self.get_queryset(), model=Blade,
                             stream=response, fields=self.columns)
        response['Content-length'] = str(len(response.content))
        return response
