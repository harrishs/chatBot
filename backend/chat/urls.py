from rest_framework.routers import DefaultRouter
from .views import CompanyViewSet, ChatBotInstanceViewSet, JiraSyncViewSet, ConfluenceSyncViewSet, ChatFeedbackViewSet

router = DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'chatBots', ChatBotInstanceViewSet)
router.register(r'jiraSyncs', JiraSyncViewSet)
router.register(r'confluenceSyncs', ConfluenceSyncViewSet)
router.register(r'feedbacks', ChatFeedbackViewSet)

urlpatterns = router.urls