"use client"

import dynamic from 'next/dynamic'
import { Suspense } from 'react'

// Create a simple wrapper component
const GradientCanvas = dynamic(
  () => import('./gradient-canvas').then(mod => mod.default),
  { 
    ssr: false,
    loading: () => (
      <div className="absolute inset-0 bg-gradient-to-b from-purple-900/20 via-blue-900/20 to-orange-900/20" />
    )
  }
)

export function GradientBackground() {
  return (
    <div className="absolute inset-x-0 top-0 h-full -z-20">
      <Suspense fallback={
        <div className="absolute -top-20 left-0 right-0 h-[calc(100%+5rem)] bg-gradient-to-b from-purple-900/20 via-blue-900/20 to-orange-900/20" />
      }>
        <div className="absolute -top-20 left-0 right-0 h-[calc(100%+5rem)]">
          <GradientCanvas />
        </div>
      </Suspense>
    </div>
  )
}