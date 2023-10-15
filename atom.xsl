<?xml version="1.0" encoding="UTF-8" ?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://www.w3.org/1999/xhtml">
    <xsl:output method="html" indent="yes" encoding="UTF-8"/>
    <xsl:template match="/atom:feed">
        <html>
            <head>
                <title>
                    <xsl:value-of select="atom:title" />
                </title>
                <link rel="stylesheet" href="feed.css"/>
                <link rel="alternate" href="/atom.xml" type="application/atom+xml" title="ATOM"/>
            </head>
            <body>
                <h1><a href="{atom:link/@href}"><xsl:value-of select="atom:title" /></a></h1>
                <ul id="feed">
                    <xsl:apply-templates select="atom:entry" />
                </ul>
                <div style="text-align:center" id="next">
                    <a  href="{atom:link[@rel='next']/@href}">Next</a>
                </div>
            </body>
        </html>
    </xsl:template>
    <xsl:template match="atom:entry">
        <li>
            <div class="source"><b>[<a href="{atom:source/atom:link[@rel='self']/@href}"><xsl:value-of select="atom:source/atom:title"/></a>@<xsl:value-of select="atom:updated"/>]</b></div> 
            <input type="checkbox" class="more" />
            <h2><a href="{atom:link[@rel='alternate'][@type='text/html']/@href}"><xsl:value-of select="atom:title"/></a></h2>
            <div class="description">
                <xsl:value-of select="atom:content" disable-output-escaping="yes"/>
            </div>
            <p>
             <xsl:apply-templates select="atom:link[@rel='enclosure']" />
            </p>
        </li>
    </xsl:template>
    <xsl:template match="atom:link[@rel='enclosure'][starts-with(@type,'image')]">
        <details>
            <summary>Image Enclosure</summary>
            <a href="{@href}" target="_blank"><img style="max-width:100%;" loading="lazy" src="{@href}"/></a>
        </details>
    </xsl:template>
    <xsl:template match="atom:link[@rel='enclosure'][starts-with(@type,'video')]">
        <details>
            <summary>Video Enclosure</summary>
            <video style="max-width:100%" controls="true" preload="none">
                <source src="{@href}" type="{@type}"/>
            </video>
        </details>
    </xsl:template>
    <xsl:template match="atom:link[@rel='enclosure'][starts-with(@type,'audio')]">
        <audio width="100%" controls="true" preload="none">
            <source src="{@href}" type="{@type}"/>
        </audio>
    </xsl:template>
</xsl:stylesheet>
