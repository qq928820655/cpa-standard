import VideoWorld from './VideoWorld.vue'

const register = ({ router, addMenuItem }) => {
  router.addRoute({
    path: '/video-world',
    name: 'VideoWorld',
    component: VideoWorld,
    meta: { requiresImageSquareAccess: true },
  })
  addMenuItem({
    path: '/video-world',
    label: '影视界',
    icon: 'VideoCamera',
    requiresImageSquareAccess: true,
  })
}

window.CpaPluginModules = window.CpaPluginModules || {}
window.CpaPluginModules['video-world'] = { register }
