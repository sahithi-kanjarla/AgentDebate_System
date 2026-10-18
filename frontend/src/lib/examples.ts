/** Example questions. Each states the answer format it wants, because answers are compared exactly. */
export interface Example {
  id: string
  title: string
  hint: string
  question: string
}

export const EXAMPLES: Example[] = [
  {
    id: 'code',
    title: 'What does this print?',
    hint: 'Code output',
    question: [
      'What does this print? Give only the printed line.',
      '',
      'def add(item, bucket=[]):',
      '    bucket.append(item)',
      '    return bucket',
      '',
      'add(1)',
      'add(2)',
      'print(add(3))',
    ].join('\n'),
  },
  {
    id: 'calculus',
    title: 'A calculus trap',
    hint: 'Math',
    question:
      'Evaluate the integral from -1 to 1 of 1/x^2 dx. If it does not converge, answer exactly: diverges. Otherwise give a decimal rounded to 4 places.',
  },
  {
    id: 'opinion',
    title: 'Split the monolith?',
    hint: 'Opinion',
    question:
      'Should a five-person startup split its working monolith into microservices? Put the reasoning in your reasoning field, and make your final answer exactly one word: split or keep.',
  },
]
