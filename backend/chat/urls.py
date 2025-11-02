from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter

from .views import (
    ChatBotInstanceViewSet,
    ChatFeedbackViewSet,
    CSRFTokenView,
    CompanyViewSet,
    ConfluenceSyncViewSet,
    CredentialViewSet,
    GitCredentialViewSet,
    GitRepoSyncViewSet,
    JiraSyncViewSet,
    LoginView,
    LogoutView,
    SessionView,
    UserViewSet,
    chat_with_bot,
    query_documents,
)

router = DefaultRouter()
router.register(r'companies', CompanyViewSet, basename='company')
router.register(r'chatBots', ChatBotInstanceViewSet, basename='chatBot')
router.register(r'feedbacks', ChatFeedbackViewSet, basename='feedback')
router.register(r'users', UserViewSet, basename='user')
router.register(r'credentials', CredentialViewSet, basename='credential')
router.register(r'gitCredentials', GitCredentialViewSet, basename='gitCredential')

jira_router = NestedDefaultRouter(router, r'chatBots', lookup='chatbot')
jira_router.register(r'jiraSyncs', JiraSyncViewSet, basename='jiraSync')

confluence_router = NestedDefaultRouter(router, r'chatBots', lookup='chatbot')
confluence_router.register(r'confluenceSyncs', ConfluenceSyncViewSet, basename='confluenceSync')

github_router = NestedDefaultRouter(router, r'chatBots', lookup='chatbot')
github_router.register(r'gitRepoSyncs', GitRepoSyncViewSet, basename='gitRepoSync')

urlpatterns = [
    path('login/', LoginView.as_view(), name='api-login'),
    path('logout/', LogoutView.as_view(), name='api-logout'),
    path('auth/session/', SessionView.as_view(), name='api-session'),
    path('csrf/', CSRFTokenView.as_view(), name='api-csrf'),
    path('', include(router.urls)),
    path('', include(jira_router.urls)),
    path('', include(confluence_router.urls)),
    path('', include(github_router.urls)),
    path('chatbots/<int:chatbot_id>/query/', query_documents),
    path('chatbots/<int:chatbot_id>/chat/', chat_with_bot),
]
