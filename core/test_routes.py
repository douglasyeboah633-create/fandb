"""Public routing smoke tests."""
from django.test import TestCase
from django.urls import reverse
from .urls import urlpatterns


class PublicRouteTests(TestCase):
    def test_public_routes(self):
        for route in urlpatterns:
            kwargs = {key: ("AVAILABLE" if key == "status" else "sales" if key == "kind" else 1)
                      for key in route.pattern.converters}
            url = reverse(f"core:{route.name}", kwargs=kwargs)
            with self.subTest(route=route.name):
                response = self.client.get(url)
                self.assertIn(response.status_code, (200, 302))
