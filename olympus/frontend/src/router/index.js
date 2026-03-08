import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/RegisterView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Global navigation guard
router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // Try to restore session from cookie on first load
  if (!authStore.isAuthenticated && !to.meta.public) {
    const ok = await authStore.refresh()
    if (!ok) {
      return { name: 'Login', query: to.path !== '/' ? { redirect: to.fullPath } : undefined }
    }
  }

  // Redirect authenticated users away from login/register
  if (authStore.isAuthenticated && to.meta.public) {
    return { name: 'Chat' }
  }

  return true
})

export default router
