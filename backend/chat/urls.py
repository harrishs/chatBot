from rest_framework.routers import DefaultRouter
from .views import CompanyViewSet, ChatBotInstanceViewSet, JiraSyncViewSet, ConfluenceSyncViewSet, ChatFeedbackViewSet, UserViewSet, CredentialViewSet
from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token

router = DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'chatBots', ChatBotInstanceViewSet, basename='chatBot')
router.register(r'feedbacks', ChatFeedbackViewSet, basename='feedback')
router.register(r'users', UserViewSet, basename='user')
router.register(r'credentials', CredentialViewSet, basename='credential')

urlpatterns = [
    path('login/', obtain_auth_token, name='api_token_auth'),
    path('', include(router.urls)),
    path('chatBots/<int:chatbot_id>/jiraSyncs/', JiraSyncViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('chatBots/<int:chatbot_id>/confluenceSyncs/', ConfluenceSyncViewSet.as_view({'get': 'list', 'post': 'create'})),
]