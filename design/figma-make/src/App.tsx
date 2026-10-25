import { useState } from 'react'

const asset = (name: string) => `/assets/${name}`

type DisclosureProps = {
  title: string
  detail: string
  tone: 'good' | 'bad' | 'warn'
  icon: string
}

function Disclosure({ title, detail, tone, icon }: DisclosureProps) {
  const [open, setOpen] = useState(true)
  const tones = {
    good: 'border-[#b8cdb8] bg-[#cbe7cb] text-[#45634d]',
    bad: 'border-[#d9b7ae] bg-[#f4ded6] text-[#a85d46]',
    warn: 'border-[#e8d2a8] bg-[#fff4e5] text-[#99721f]',
  }

  return (
    <button
      className={`w-full rounded-lg border px-[14px] py-3 text-left ${tones[tone]}`}
      onClick={() => setOpen((value) => !value)}
      aria-expanded={open}
    >
      <span className="flex items-center justify-between">
        <span className="font-['Inter:Semi_Bold'] text-[15px] leading-[1.4]">{title}</span>
        <img
          src={asset(icon)}
          alt=""
          className={`size-[14px] transition-transform ${open ? '' : '-rotate-90'}`}
        />
      </span>
      {open && (
        <span className="mt-1.5 block font-['Inter:Regular'] text-[14px] leading-[1.4] text-[#302d27]">
          {detail}
        </span>
      )}
    </button>
  )
}

export default function App() {
  const [tab, setTab] = useState<'product' | 'shortlist'>('product')

  return (
    <main className="flex min-h-dvh w-full flex-col bg-[#f6f1e8] text-[#2a2117]">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#d8c7a8] bg-[#e8d8be] px-5">
        <div className="flex min-w-0 items-center gap-[9px]">
          <span className="flex size-[27px] shrink-0 items-center justify-center rounded-[5px] bg-[#efcb7f]">
            <img src={asset('8054c.svg')} alt="" className="size-5" />
          </span>
          <h1 className="truncate font-['Press_Start_2P:Regular'] text-[20px] leading-normal">
            Khai’s CTO
          </h1>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            className="flex size-8 items-center justify-center rounded-lg border border-[#d8c7a8] bg-[#f1e4d0]"
            aria-label="Open in new window"
          >
            <img src={asset('f4ba9.svg')} alt="" className="size-5" />
          </button>
          <button
            className="flex size-8 items-center justify-center rounded-lg border border-[#d8c7a8] bg-[#f1e4d0]"
            aria-label="Close"
          >
            <img src={asset('ddda7.svg')} alt="" className="size-5" />
          </button>
        </div>
      </header>

      <section className="shrink-0 bg-[#efcb7f] px-5 py-3.5">
        <div className="flex items-center justify-between">
          <h2 className="font-['Inter:Semi_Bold'] text-[15px] leading-[1.4]">Home office</h2>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 font-['Inter:Regular'] text-sm">
              <span className="flex size-[18px] items-center justify-center rounded-full border border-[#d8c7a8] bg-[#f1e4d0]">
                <img src={asset('455a2.svg')} alt="" className="size-3" />
              </span>
              Not saved
            </span>
            <button aria-label="Edit project">
              <img src={asset('d762e.svg')} alt="" className="size-5" />
            </button>
            <button aria-label="Save project">
              <img src={asset('c448e.svg')} alt="" className="h-[17px] w-[22px]" />
            </button>
          </div>
        </div>
        <div className="mt-3 flex h-11 rounded-[10px] bg-[#e8d8be] p-[3px]">
          {[
            ['product', 'This product'],
            ['shortlist', 'Shortlist · 6'],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setTab(value as 'product' | 'shortlist')}
              className={`flex-1 rounded-lg px-3 text-center text-sm leading-[1.4] ${
                tab === value
                  ? "bg-[#fffefa] font-['Inter:Semi_Bold'] shadow-[0_1px_3px_rgba(0,0,0,.1)]"
                  : "font-['Inter:Medium'] text-[#303036]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-1 flex-col gap-5 bg-[#f3efe6] p-6">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-2xl bg-[#f5eedb]">
            <img src={asset('6d38a.svg')} alt="" className="size-[18px]" />
          </span>
          <h2 className="font-['Inter:Semi_Bold'] text-[15px] leading-[1.4]">CTO</h2>
        </div>

        {tab === 'product' ? (
          <div className="relative flex flex-col gap-3 rounded-xl border border-[#dcd5c8] bg-[#fffcf6] p-4">
            <span className="absolute left-[29px] top-[-9px] size-4 -rotate-45 border border-[#dcd5c8] bg-[#fffcf6]" />
            <div className="relative flex flex-col items-center gap-2.5 rounded-[10px] border border-[#dcd5c8] bg-[#fffcf6] px-5 pb-5 pt-6 shadow-[0_2px_8px_rgba(0,0,0,.12)]">
              <div className="w-full text-center">
                <p className="font-['Happy_Monkey:Regular'] text-[80px] leading-[90px] tracking-[-5px] text-[#302d27]">
                  68%
                </p>
                <p className="font-['Inter:Semi_Bold'] text-sm leading-[1.4] text-[#99721f]">
                  Conditional fit
                </p>
              </div>
              <p className="w-full text-center font-['Inter:Semi_Bold'] text-sm leading-[1.4] text-[#302d27]">
                Swap arm + dock to fit this monitor.
              </p>
              <div className="w-full rounded-lg border border-[#dcd5c8] p-3">
                <div className="flex items-center justify-between text-[#302d27]">
                  <span className="font-['Inter:Semi_Bold'] text-lg leading-[1.4]">Canvas 32 4K</span>
                  <span className="font-['Inter:Regular'] text-[17px] leading-[1.4]">$419</span>
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Disclosure
                tone="good"
                title="Pros"
                detail="More room · 4K at 60 Hz · VESA 100"
                icon="1c6b7.svg"
              />
              <Disclosure
                tone="bad"
                title="Cons · 2 incompatible"
                detail="Lift S load limit exceeded · D1: 4K / 30 Hz"
                icon="81b0f.svg"
              />
              <Disclosure
                tone="warn"
                title="Missing spec · 1 unverified"
                detail="USB-C charging not listed"
                icon="7d8a0.svg"
              />
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-[#dcd5c8] bg-[#fffcf6] p-6 text-center">
            <p className="font-['Inter:Semi_Bold'] text-base">6 shortlisted products</p>
            <p className="mt-2 font-['Inter:Regular'] text-sm text-[#5c4a3a]">
              Open the project plan to compare your saved options.
            </p>
          </div>
        )}
      </section>

      <footer className="sticky bottom-0 flex shrink-0 flex-col gap-3 bg-[#d8b35a] px-6 pb-5 pt-4">
        <div className="flex flex-col gap-3 rounded-[10px] border border-[#b7791f] bg-[#f7f1e4] px-4 py-3.5">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-['Inter:Regular'] text-sm">Setup total</span>
              <strong className="font-['Inter:Semi_Bold'] text-2xl">$737</strong>
            </div>
            <p className="font-['Inter:Regular'] text-sm text-[#4a4035]">
              Includes compatible arm + dock
            </p>
          </div>
          <div className="h-px bg-[#b7791f]" />
          <div className="space-y-[7px] text-sm leading-[1.4]">
            <div className="flex justify-between font-['Inter:Semi_Bold']">
              <span className="text-[#4a4035]">Budget remaining</span>
              <span className="text-[#2a5a3b]">$113</span>
            </div>
            <div className="flex justify-between font-['Inter:Regular']">
              <span className="text-[#4a4035]">Change from current</span>
              <span className="text-[#5c4a3a]">+$260</span>
            </div>
          </div>
        </div>
        <button className="flex items-center justify-center gap-1.5 font-['Inter:Semi_Bold'] text-sm text-[#8a4a1f]">
          Open project plan
          <img src={asset('6ae2d.svg')} alt="" className="size-3.5" />
        </button>
      </footer>
    </main>
  )
}
