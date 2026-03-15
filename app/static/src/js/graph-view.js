export async function mountGraphView(root) {
  if (!root) return
  root.innerHTML = '<div class="text-sm text-slate-600">Graph view placeholder. Connect a renderer here.</div>'
}
