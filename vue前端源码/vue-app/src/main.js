import { createApp } from 'vue'
import './style.css'
import RootApp from './RootApp.vue'
import router from './router.js'

const app = createApp(RootApp)
app.use(router)
router.isReady().then(() => app.mount('#app'))
