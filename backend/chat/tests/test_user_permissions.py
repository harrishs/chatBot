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
        self.staff_user.role = User.Role.ADMIN
        self.staff_user.save()

        self.regular_user = User.objects.create_user(
            username="jane",
            email="jane@example.com",
            password="password123",
        )
        self.regular_user.company = self.company
        self.regular_user.is_staff = False
        self.regular_user.role = User.Role.VIEWER
        self.regular_user.save()

        self.company_admin = User.objects.create_user(
            username="company-admin",
            email="company-admin@example.com",
            password="password123",
        )
        self.company_admin.company = self.company
        self.company_admin.is_staff = False
        self.company_admin.role = User.Role.ADMIN
        self.company_admin.save()

        self.existing_user = User.objects.create_user(
            username="john",
            email="john@example.com",
            password="password123",
        )
        self.existing_user.company = self.company
        self.existing_user.role = User.Role.ADMIN
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

    def test_company_admin_can_manage_users_in_company(self):
        self.client.force_authenticate(self.company_admin)

        create_response = self.client.post(
            reverse("user-list"),
            {"username": "team-member", "email": "team@example.com", "password": "password123"},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        managed_user_id = create_response.data["id"]

        patch_response = self.client.patch(
            reverse("user-detail", args=[managed_user_id]),
            {"email": "team-update@example.com"},
            format="json",
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(reverse("user-detail", args=[managed_user_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=managed_user_id).exists())

    def test_staff_user_can_create_viewer(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            reverse("user-list"),
            {
                "username": "viewer",
                "email": "viewer@example.com",
                "password": "password123",
                "role": User.Role.VIEWER,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        viewer = User.objects.get(id=response.data["id"])
        self.assertEqual(viewer.role, User.Role.VIEWER)

    def test_staff_user_can_promote_and_demote_roles(self):
        self.client.force_authenticate(self.staff_user)
        target_user = User.objects.create_user(
            username="target",
            email="target@example.com",
            password="password123",
        )
        target_user.company = self.company
        target_user.role = User.Role.VIEWER
        target_user.save()

        promote_response = self.client.patch(
            reverse("user-detail", args=[target_user.id]),
            {"role": User.Role.ADMIN},
            format="json",
        )
        self.assertEqual(promote_response.status_code, status.HTTP_200_OK)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Role.ADMIN)

        demote_response = self.client.patch(
            reverse("user-detail", args=[target_user.id]),
            {"role": User.Role.VIEWER},
            format="json",
        )
        self.assertEqual(demote_response.status_code, status.HTTP_200_OK)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Role.VIEWER)

    def test_viewer_cannot_promote_self_to_admin(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.patch(
            reverse("user-detail", args=[self.regular_user.id]),
            {"role": User.Role.ADMIN},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.role, User.Role.VIEWER)

    def test_viewer_can_update_their_own_profile(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.patch(
            reverse("user-detail", args=[self.regular_user.id]),
            {"email": "jane-update@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.email, "jane-update@example.com")


class CompanyViewSetPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company_one = Company.objects.create(name="Company One")
        self.company_two = Company.objects.create(name="Company Two")

        self.staff_user = User.objects.create_user(
            username="company-staff",
            email="staff@example.com",
            password="password123",
        )
        self.staff_user.company = self.company_one
        self.staff_user.is_staff = True
        self.staff_user.save()

        self.superuser = User.objects.create_superuser(
            username="super-admin",
            email="super@example.com",
            password="password123",
        )

    def test_staff_user_only_lists_their_company(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.get(reverse("company-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.company_one.id)

    def test_staff_user_cannot_retrieve_other_company(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.get(reverse("company-detail", args=[self.company_two.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_superuser_lists_all_companies(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.get(reverse("company-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {company["id"] for company in response.data}
        self.assertSetEqual(returned_ids, {self.company_one.id, self.company_two.id})

    def test_superuser_can_retrieve_any_company(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.get(reverse("company-detail", args=[self.company_two.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.company_two.id)
