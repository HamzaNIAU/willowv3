"use client"

import dynamic from 'next/dynamic'

const GradientVanilla = dynamic(
  () => import('./gradient-vanilla'),
  { ssr: false }
)

export default function GradientCanvas() {
  return <GradientVanilla />
}