import { useEffect } from 'react'

export function useRevealObserver(deps = []) {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.05, rootMargin: '0px 0px -8px 0px' }
    )

    const id = setTimeout(() => {
      document.querySelectorAll('.animate-reveal:not(.is-visible)')
        .forEach((el) => observer.observe(el))
    }, 50)

    return () => {
      clearTimeout(id)
      observer.disconnect()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
