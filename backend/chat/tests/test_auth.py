from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


User = get_user_model()


class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.password = 'super-secret-password'
        self.user = User.objects.create_user(
            username='jane',
            email='jane@example.com',
            password=self.password,
        )

    def test_login_sets_secure_session_cookie(self):
        response = self.client.post(
            reverse('api-login'),
            {'username': self.user.username, 'password': self.password},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        session_cookie = response.cookies.get('sessionid')
        self.assertIsNotNone(session_cookie)
        self.assertTrue(session_cookie['secure'])
        self.assertTrue(session_cookie['httponly'])

    def test_session_endpoint_returns_user_after_login(self):
        self.client.post(
            reverse('api-login'),
            {'username': self.user.username, 'password': self.password},
            format='json',
        )

        session_response = self.client.get(reverse('api-session'))

        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        self.assertEqual(session_response.data['username'], self.user.username)

    def test_logout_clears_session_cookie_and_denies_session(self):
        self.client.post(
            reverse('api-login'),
            {'username': self.user.username, 'password': self.password},
            format='json',
        )

        logout_response = self.client.post(reverse('api-logout'))
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)
        deleted_cookie = logout_response.cookies.get('sessionid')
        self.assertIsNotNone(deleted_cookie)
        self.assertEqual(int(deleted_cookie['max-age']), 0)

        session_response = self.client.get(reverse('api-session'))
        self.assertEqual(session_response.status_code, status.HTTP_401_UNAUTHORIZED)
