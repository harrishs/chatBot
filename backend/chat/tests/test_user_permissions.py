from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from chat.models import Company


User = get_user_model()


class UserViewSetPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Acme Corp")

        self.staff_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.staff_user.company = self.company
        self.staff_user.is_staff = True
        self.staff_user.save()

        self.regular_user = User.objects.create_user(
            username="jane",
            email="jane@example.com",
            password="password123",
        )
        self.regular_user.company = self.company
        self.regular_user.is_staff = False
        self.regular_user.save()

        self.existing_user = User.objects.create_user(
            username="john",
            email="john@example.com",
            password="password123",
        )
        self.existing_user.company = self.company
        self.existing_user.save()

    def test_non_staff_user_cannot_create_user(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.post(
            reverse("user-list"),
            {"username": "newuser", "email": "new@example.com", "password": "password123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_non_staff_user_cannot_update_user(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.patch(
            reverse("user-detail", args=[self.existing_user.id]),
            {"email": "updated@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.existing_user.refresh_from_db()
        self.assertEqual(self.existing_user.email, "john@example.com")

    def test_non_staff_user_cannot_delete_user(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.delete(reverse("user-detail", args=[self.existing_user.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(User.objects.filter(id=self.existing_user.id).exists())

    def test_staff_user_can_manage_users_in_company(self):
        self.client.force_authenticate(self.staff_user)

        create_response = self.client.post(
            reverse("user-list"),
            {"username": "managed", "email": "managed@example.com", "password": "password123"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        managed_user_id = create_response.data["id"]

        patch_response = self.client.patch(
            reverse("user-detail", args=[managed_user_id]),
            {"email": "managed-update@example.com"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(reverse("user-detail", args=[managed_user_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=managed_user_id).exists())
