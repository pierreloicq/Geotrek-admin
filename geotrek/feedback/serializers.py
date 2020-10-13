from django.contrib.gis.geos import GEOSGeometry
from rest_framework import serializers as rest_serializers
from rest_framework_gis.fields import GeometryField
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from geotrek.feedback import models as feedback_models


class ReportSerializer(rest_serializers.ModelSerializer):
    class Meta:
        model = feedback_models.Report
        id_field = 'id'
        fields = ('id', 'email', 'activity', 'comment', 'category',
                  'status', 'problem_magnitude', 'related_trek',
                  'geom')
        extra_kwargs = {
            'geom': {'write_only': True},
        }

    def validate_geom(self, value):
        return GEOSGeometry(value, srid=4326)


class ReportGeojsonSerializer(GeoFeatureModelSerializer, ReportSerializer):
    # Annotated geom field with API_SRID
    api_geom = GeometryField(read_only=True, precision=7)

    class Meta(ReportSerializer.Meta):
        geo_field = 'api_geom'
        fields = ReportSerializer.Meta.fields + ('api_geom', )


class ReportActivitySerializer(rest_serializers.ModelSerializer):
    class Meta:
        model = feedback_models.ReportActivity
        fields = ['id', 'label']


class ReportCategorySerializer(rest_serializers.ModelSerializer):
    class Meta:
        model = feedback_models.ReportCategory
        fields = ['id', 'label']


class ReportProblemMagnitudeSerializer(rest_serializers.ModelSerializer):
    class Meta:
        model = feedback_models.ReportProblemMagnitude
        fields = ['id', 'label']
