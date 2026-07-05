import { computed, type Ref } from 'vue'

// 把 attrs 对象里的某个字段做成可写 computed（编辑器里 v-model 用）。
// 每次 set 都返回新对象 → 触发 v-model:attrs 回传，类型安全。
export function attrField<T = any>(model: Ref<Record<string, any> | undefined>, key: string) {
  return computed<T>({
    get: () => (model.value?.[key] as T),
    set: (v: T) => {
      model.value = { ...(model.value || {}), [key]: v }
    },
  })
}
