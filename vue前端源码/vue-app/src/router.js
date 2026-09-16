import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import LoginView from './views/LoginView.vue'
import { auth } from './services/auth.js'

// App remains the shared shell for every page.  Explicit health routes make
// /health and /health-detail bookmarkable while the shell keeps its legacy
// hash navigation for features whose APIs are not implemented yet.
export const routes = [
  { path: '/login', name: 'login', component: LoginView },
  { path: '/', name: 'shell', component: App },
  { path: '/health', name: 'health', component: App },
  { path: '/health-detail', name: 'health-detail', component: App },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const loggedIn = Boolean(auth.token) && (!auth.expiresAt || auth.expiresAt > Date.now())
  if (to.path === '/login' && loggedIn) return '/'
  if (to.path !== '/login' && !loggedIn) return '/login'
  return true
})

export default router
