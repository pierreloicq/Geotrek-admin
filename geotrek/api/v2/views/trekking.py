from __future__ import unicode_literals

from django.conf import settings
from django.db.models import F
from django.db.models.aggregates import Count
from django.http import JsonResponse
from rest_framework import response, decorators, viewsets, permissions
from rest_framework_extensions.mixins import DetailSerializerMixin

from geotrek.api.v2 import serializers as api_serializers, \
    viewsets as api_viewsets
from geotrek.api.v2.functions import Transform, Length, Length3D
from geotrek.trekking import models as trekking_models
from geotrek.common import models as common_models

def mobile_filters_view(request):
    practices = {practice.pk: practice.name for practice in trekking_models.Practice.objects.all()}
    difficulties = {difficulty.pk: {'name': difficulty.difficulty, 'pictogram': difficulty.pictogram.url} for difficulty in trekking_models.DifficultyLevel.objects.all()}
    durations = ((0, 0.5), (0.5, 1), (1, None))
    elevations = ((0, 300), (300, 600), (600, 1000), (1000, None))
    lengths = ((0, 10), (10, 20), (20, 30), (30, None))
    themes = {theme.pk: { 'label': theme.label, 'pictogram': theme.pictogram.url} for theme in common_models.Theme.objects.all()}
    
    return JsonResponse({'practices': practices, 'difficulties': difficulties, 'durations': durations, 'elevations': elevations, 'lengths': lengths, 'themes': themes, 'lengths':lengths})

def mobile_poi_types_view(request):
    types = {type.pk: {'pictogram': type.pictogram.url} for type in trekking_models.POIType.objects.all()}

    return JsonResponse({'types': types})

def mobile_practices_view(request):
    practices = {practice.pk: { 'name': practice.name, 'pictogram': practice.pictogram.url} for practice in trekking_models.Practice.objects.all()}

    return JsonResponse({'practices': practices})

class MobileTrekViewSet(DetailSerializerMixin, viewsets.ReadOnlyModelViewSet):
    queryset = trekking_models.Trek.objects.filter(published=True, deleted=False)
    serializer_class = api_serializers.MobileTrekListSerializer
    serializer_detail_class = api_serializers.MobileTrekDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly ]

class TrekViewSet(api_viewsets.GeotrekViewset):
    serializer_class = api_serializers.TrekListSerializer
    serializer_detail_class = api_serializers.TrekDetailSerializer
    queryset = trekking_models.Trek.objects.existing() \
        .select_related('topo_object', 'difficulty', 'practice') \
        .prefetch_related('topo_object__aggregations', 'themes', 'networks', 'attachments') \
        .annotate(geom2d_transformed=Transform(F('geom'), settings.API_SRID),
                  geom3d_transformed=Transform(F('geom_3d'), settings.API_SRID),
                  length_2d_m=Length('geom'),
                  length_3d_m=Length3D('geom_3d')) \
        .order_by('pk')  # Required for reliable pagination
    filter_fields = ('difficulty', 'themes', 'networks', 'practice')

    @decorators.list_route(methods=['get'])
    def all_practices(self, request, *args, **kwargs):
        """
        Get all practices list
        """
        data = api_serializers.TrekPracticeSerializer(trekking_models.Practice.objects.all(),
                                                      many=True,
                                                      context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def used_practices(self, request, *args, **kwargs):
        """
        Get practices used by Trek instances
        """
        data = api_serializers.TrekPracticeSerializer(trekking_models.Practice.objects.filter(
            pk__in=trekking_models.Trek.objects.existing().values_list('practice_id', flat=True)),
            many=True,
            context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def all_themes(self, request, *args, **kwargs):
        """
        Get all themes list
        """
        data = api_serializers.TrekThemeSerializer(trekking_models.Theme.objects.all(),
                                                   many=True,
                                                   context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def used_themes(self, request, *args, **kwargs):
        """
        Get themes used by Trek instances
        """
        data = api_serializers.TrekThemeSerializer(trekking_models.Theme.objects.filter(
            pk__in=trekking_models.Trek.objects.existing().values_list('themes', flat=True)),
            many=True,
            context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def all_networks(self, request, *args, **kwargs):
        """
        Get all networks list
        """
        data = api_serializers.TrekNetworkSerializer(trekking_models.TrekNetwork.objects.all(),
                                                     many=True,
                                                     context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def used_networks(self, request, *args, **kwargs):
        """
        Get networks used by Trek instances
        """
        data = api_serializers.TrekNetworkSerializer(trekking_models.TrekNetwork.objects.filter(
            pk__in=trekking_models.Trek.objects.existing().values_list('networks', flat=True)),
            many=True,
            context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def all_difficulties(self, request, *args, **kwargs):
        """
        Get all difficulties list
        """
        qs = trekking_models.DifficultyLevel.objects.all()
        data = api_serializers.DifficultySerializer(qs, many=True, context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def used_difficulties(self, request, *args, **kwargs):
        """
        Get difficulties used by Trek instances
        """
        data = api_serializers.DifficultySerializer(trekking_models.DifficultyLevel.objects.filter(
            pk__in=trekking_models.Trek.objects.existing().values_list('difficulty_id', flat=True)),
            many=True,
            context={'request': request}).data
        return response.Response(data)


class TourViewSet(TrekViewSet):
    serializer_class = api_serializers.TourListSerializer
    serializer_detail_class = api_serializers.TourDetailSerializer
    queryset = TrekViewSet.queryset.annotate(count_children=Count('trek_children')) \
        .filter(count_children__gt=0)


class POIViewSet(api_viewsets.GeotrekViewset):
    serializer_class = api_serializers.POIListSerializer
    serializer_detail_class = api_serializers.POIDetailSerializer
    queryset = trekking_models.POI.objects.existing() \
        .select_related('topo_object', 'type', ) \
        .prefetch_related('topo_object__aggregations', 'attachments') \
        .annotate(geom2d_transformed=Transform(F('geom'), settings.API_SRID),
                  geom3d_transformed=Transform(F('geom_3d'), settings.API_SRID)) \
        .order_by('pk')  # Required for reliable pagination
    filter_fields = ('type',)

    @decorators.list_route(methods=['get'])
    def all_types(self, request, *args, **kwargs):
        """
        Get all POI types
        """
        data = api_serializers.POITypeSerializer(trekking_models.POIType.objects.all(),
                                                 many=True,
                                                 context={'request': request}).data
        return response.Response(data)

    @decorators.list_route(methods=['get'])
    def used_types(self, request, *args, **kwargs):
        """
        Get POI types used by POI instances
        """
        data = api_serializers.POITypeSerializer(
            trekking_models.POIType.objects.filter(pk__in=trekking_models.POI.objects.existing()
                                                   .values_list('type_id', flat=True)),
            many=True,
            context={'request': request}).data
        return response.Response(data)
