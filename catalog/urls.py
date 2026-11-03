from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("instances", views.InstanceListView.as_view(), name="instance-list"),
    path(
        "instances/<int:pk>",
        views.InstanceDetailView.as_view(),
        name="instance-detail",
    ),
    path("datacenters", views.DatacenterListView.as_view(), name="datacenter-list"),
    path(
        "datacenters/<int:pk>",
        views.DatacenterDetailView.as_view(),
        name="datacenter-detail",
    ),
    path(
        "datacenters/<int:pk>/instances",
        views.DatacenterInstancesView.as_view(),
        name="datacenter-instances",
    ),
    path("vendors", views.VendorListView.as_view(), name="vendor-list"),
    path("vendors/<int:pk>", views.VendorDetailView.as_view(), name="vendor-detail"),
    path(
        "vendors/<int:pk>/instances",
        views.VendorInstancesView.as_view(),
        name="vendor-instances",
    ),
]
