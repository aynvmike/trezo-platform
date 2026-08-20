import { motion } from "motion/react";

// Seven orbital shells — outer (1, most volatile) → inner (7, treasure vault)
const shells = [
  { id: 1, rotX: 70, rotY: 0, size: 360, electronColor: "var(--rose)" },
  { id: 2, rotX: 60, rotY: 30, size: 320, electronColor: "var(--amber)" },
  { id: 3, rotX: 50, rotY: 60, size: 280, electronColor: "var(--sky)" },
  { id: 4, rotX: 75, rotY: 90, size: 240, electronColor: "var(--treasure)" },
  { id: 5, rotX: 65, rotY: 120, size: 200, electronColor: "var(--emerald)" },
  { id: 6, rotX: 55, rotY: 150, size: 160, electronColor: "var(--sky)" },
  { id: 7, rotX: 45, rotY: 180, size: 120, electronColor: "var(--treasure)" },
];

export function AtomHero({ size = 480 }: { size?: number }) {
  return (
    <div
      className="relative flex items-center justify-center"
      style={{
        width: size,
        height: size,
        perspective: "1200px",
      }}
    >
      {/* Glow halo */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: size * 0.6,
          height: size * 0.6,
          background: "radial-gradient(circle, var(--treasure) 0%, transparent 60%)",
          opacity: 0.18,
          filter: "blur(40px)",
        }}
        animate={{ scale: [1, 1.15, 1], opacity: [0.16, 0.28, 0.16] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Tumbling group */}
      <motion.div
        className="relative"
        style={{
          width: size,
          height: size,
          transformStyle: "preserve-3d",
        }}
        animate={{
          rotateX: [0, 15, -10, 0],
          rotateY: [0, 360],
          rotateZ: [0, 5, -5, 0],
        }}
        transition={{
          rotateY: { duration: 40, repeat: Infinity, ease: "linear" },
          rotateX: { duration: 18, repeat: Infinity, ease: "easeInOut" },
          rotateZ: { duration: 22, repeat: Infinity, ease: "easeInOut" },
        }}
      >
        {/* Shells with electrons */}
        {shells.map((shell, i) => {
          const orbitalRadius = shell.size / 2;
          return (
            <div
              key={shell.id}
              className="absolute top-1/2 left-1/2 rounded-full"
              style={{
                width: shell.size,
                height: shell.size,
                marginLeft: -shell.size / 2,
                marginTop: -shell.size / 2,
                transform: `rotateX(${shell.rotX}deg) rotateY(${shell.rotY}deg)`,
                transformStyle: "preserve-3d",
                border: "1px solid rgba(196, 150, 74, 0.35)",
                boxShadow: `inset 0 0 ${shell.size / 6}px rgba(196, 150, 74, 0.08)`,
              }}
            >
              {/* Electron — orbiting on the shell */}
              <motion.div
                className="absolute top-1/2 left-1/2"
                style={{
                  width: 0,
                  height: 0,
                  transformStyle: "preserve-3d",
                }}
                animate={{ rotateZ: 360 }}
                transition={{
                  duration: 6 + i * 1.4,
                  repeat: Infinity,
                  ease: "linear",
                }}
              >
                <div
                  className="absolute rounded-full"
                  style={{
                    width: 10 - i * 0.6,
                    height: 10 - i * 0.6,
                    background: `radial-gradient(circle at 30% 30%, white 0%, ${shell.electronColor} 40%, transparent 100%)`,
                    boxShadow: `0 0 12px ${shell.electronColor}`,
                    left: orbitalRadius - 5,
                    top: -5,
                  }}
                />
              </motion.div>

              {/* Second electron offset */}
              <motion.div
                className="absolute top-1/2 left-1/2"
                style={{
                  width: 0,
                  height: 0,
                  transformStyle: "preserve-3d",
                }}
                animate={{ rotateZ: -360 }}
                transition={{
                  duration: 8 + i * 1.2,
                  repeat: Infinity,
                  ease: "linear",
                  delay: i * 0.3,
                }}
              >
                <div
                  className="absolute rounded-full"
                  style={{
                    width: 6,
                    height: 6,
                    background: `radial-gradient(circle at 30% 30%, white 0%, ${shell.electronColor} 50%, transparent 100%)`,
                    boxShadow: `0 0 8px ${shell.electronColor}`,
                    left: -orbitalRadius - 3,
                    top: -3,
                    opacity: 0.7,
                  }}
                />
              </motion.div>
            </div>
          );
        })}

        {/* Nucleus — the treasure core */}
        <div
          className="absolute top-1/2 left-1/2 rounded-full"
          style={{
            width: 56,
            height: 56,
            marginLeft: -28,
            marginTop: -28,
            transformStyle: "preserve-3d",
          }}
        >
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{
              background: "radial-gradient(circle at 30% 30%, #f5d99a 0%, var(--treasure) 45%, #6b4a1e 100%)",
              boxShadow: "0 0 40px var(--treasure), inset -4px -8px 16px rgba(0,0,0,0.4)",
            }}
            animate={{
              scale: [1, 1.08, 1],
              boxShadow: [
                "0 0 30px var(--treasure), inset -4px -8px 16px rgba(0,0,0,0.4)",
                "0 0 60px var(--treasure), inset -4px -8px 16px rgba(0,0,0,0.4)",
                "0 0 30px var(--treasure), inset -4px -8px 16px rgba(0,0,0,0.4)",
              ],
            }}
            transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
      </motion.div>
    </div>
  );
}
